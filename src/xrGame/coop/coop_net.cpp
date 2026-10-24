#include "stdafx.h"
#include "coop_net.h"
#include "coop_map.h"
#include "coop_world.h"
#include "Level.h"
#include "Actor.h"

#include <winsock2.h>
#include <ws2tcpip.h>
#include <thread>
#include <mutex>
#include <atomic>
#include <deque>

#pragma comment(lib, "ws2_32.lib")

namespace coop
{
	const u32 PING_INTERVAL_MS = 1000;
	const u32 ACTOR_STATE_INTERVAL_MS = 100;

	enum EState
	{
		eIdle,
		eConnecting,
		eConnected,
		eFailed,
	};

	// Socket reads happen on a worker thread, everything else on the main thread.
	class CClient : public pureFrame
	{
	public:
		~CClient() { close(); }

		bool start(LPCSTR host, u16 port, LPCSTR name);
		void stop();
		void status() const;
		bool busy() const { return m_state != eIdle; }
		bool welcomed() const { return m_welcomed; }
		u32 id() const { return m_client_id; }
		const peers_t& peers() const { return m_peers; }
		void send(NET_Packet& P);

		virtual void _BCL OnFrame();

	private:
		void worker();
		void close();
		bool recv_all(void* dst, u32 size);
		void handle(NET_Packet& P);
		void send_actor_state();

		SOCKET m_socket = INVALID_SOCKET;
		std::thread m_thread;
		std::atomic<int> m_state = eIdle;
		bool m_hello_sent = false;
		bool m_welcomed = false;

		// raw NET_Packet bytes, parsed on the main thread
		std::mutex m_inbox_lock;
		std::deque<xr_vector<u8>> m_inbox;

		xr_string m_host;
		u16 m_port = 0;
		xr_string m_name;
		xr_string m_error;

		u32 m_client_id = 0;
		u32 m_last_ping = 0;
		u32 m_last_actor_state = 0;
		u32 m_rtt = 0;

		peers_t m_peers;
	};

	static CClient g_client;

	bool CClient::start(LPCSTR host, u16 port, LPCSTR name)
	{
		static bool wsa_ready = false;
		if (!wsa_ready)
		{
			WSADATA wsa;
			if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
			{
				Msg("! [coop] WSAStartup failed");
				return false;
			}
			wsa_ready = true;
		}

		m_host = host;
		m_port = port;
		m_name = name;
		m_error.clear();
		m_hello_sent = false;
		m_welcomed = false;
		m_client_id = 0;
		m_rtt = 0;
		m_inbox.clear();
		m_peers.clear();

		// created here so that close() can always interrupt the worker, even mid-connect
		m_socket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
		if (m_socket == INVALID_SOCKET)
		{
			Msg("! [coop] can't create socket");
			return false;
		}

		m_state = eConnecting;
		m_thread = std::thread(&CClient::worker, this);
		Device.seqFrame.Add(this);

		Msg("[coop] connecting to %s:%u as '%s'", host, port, name);
		return true;
	}

	void CClient::close()
	{
		if (m_socket != INVALID_SOCKET)
		{
			shutdown(m_socket, SD_BOTH);
			closesocket(m_socket);
			m_socket = INVALID_SOCKET;
		}
		if (m_thread.joinable())
			m_thread.join();
	}

	void CClient::stop()
	{
		close();
		Device.seqFrame.Remove(this);
		m_state = eIdle;
		m_welcomed = false;
		m_peers.clear();
		clear_map_markers();
	}

	void CClient::status() const
	{
		switch (m_state)
		{
		case eIdle: Msg("[coop] status: idle"); break;
		case eConnecting: Msg("[coop] status: connecting to %s:%u", m_host.c_str(), m_port); break;
		case eConnected:
			Msg("[coop] status: connected to %s:%u, id=%u, rtt=%u ms", m_host.c_str(), m_port, m_client_id, m_rtt);
			for (const auto& [id, peer] : m_peers)
				Msg("[coop]   peer %u '%s' on %s at [%.1f %.1f %.1f]", id, peer.name.c_str(), peer.level.c_str(),
				    VPUSH(peer.position));
			break;
		case eFailed: Msg("[coop] status: failed (%s)", m_error.c_str()); break;
		}
	}

	void CClient::worker()
	{
		addrinfo hints = {};
		hints.ai_family = AF_INET;
		hints.ai_socktype = SOCK_STREAM;
		hints.ai_protocol = IPPROTO_TCP;

		string16 port;
		xr_sprintf(port, "%u", m_port);

		addrinfo* addr = nullptr;
		if (getaddrinfo(m_host.c_str(), port, &hints, &addr) != 0 || !addr)
		{
			m_error = "can't resolve host";
			m_state = eFailed;
			return;
		}

		int res = ::connect(m_socket, addr->ai_addr, (int)addr->ai_addrlen);
		freeaddrinfo(addr);
		if (res != 0)
		{
			m_error = "can't connect";
			m_state = eFailed;
			return;
		}

		BOOL nodelay = TRUE;
		setsockopt(m_socket, IPPROTO_TCP, TCP_NODELAY, (const char*)&nodelay, sizeof(nodelay));

		m_state = eConnected;

		while (true)
		{
			u32 size;
			if (!recv_all(&size, sizeof(size)))
				break;
			if (size < sizeof(u16) || size > NET_PacketSizeLimit)
			{
				m_error = "bad message size";
				break;
			}

			xr_vector<u8> msg(size);
			if (!recv_all(msg.data(), size))
				break;

			std::lock_guard<std::mutex> lock(m_inbox_lock);
			m_inbox.push_back(std::move(msg));
		}

		if (m_error.empty())
			m_error = "connection closed";
		m_state = eFailed;
	}

	bool CClient::recv_all(void* dst, u32 size)
	{
		char* p = (char*)dst;
		while (size)
		{
			int n = recv(m_socket, p, (int)size, 0);
			if (n <= 0)
				return false;
			p += n;
			size -= n;
		}
		return true;
	}

	void CClient::send(NET_Packet& P)
	{
		if (m_state != eConnected)
			return;

		xr_vector<u8> buf(sizeof(u32) + P.B.count);
		*(u32*)buf.data() = P.B.count;
		memcpy(buf.data() + sizeof(u32), P.B.data, P.B.count);

		const char* p = (const char*)buf.data();
		int left = (int)buf.size();
		while (left > 0)
		{
			int n = ::send(m_socket, p, left, 0);
			if (n <= 0)
				return; // worker notices the broken socket and reports it
			p += n;
			left -= n;
		}
	}

	void CClient::handle(NET_Packet& P)
	{
		u16 type;
		P.r_begin(type);

		switch (type)
		{
		case M_WELCOME:
			m_client_id = P.r_u32();
			m_welcomed = true;
			Msg("[coop] connected to %s:%u, id=%u", m_host.c_str(), m_port, m_client_id);
			break;
		case M_PONG:
			m_rtt = Device.dwTimeContinual - P.r_u32();
			break;
		case M_PEER_STATE:
		{
			u32 id = P.r_u32();
			auto [it, inserted] = m_peers.try_emplace(id);
			SPeer& peer = it->second;
			P.r_stringZ(peer.name);
			P.r_stringZ(peer.level);
			P.r_vec3(peer.position);
			P.r_float(peer.yaw);
			peer.last_update = Device.dwTimeContinual;
			if (inserted)
				Msg("[coop] '%s' (id=%u) is on %s", peer.name.c_str(), id, peer.level.c_str());
			break;
		}
		case M_ENTITY_DEATH:
			apply_entity_death(P);
			break;
		case M_PEER_LEFT:
		{
			u32 id = P.r_u32();
			auto it = m_peers.find(id);
			if (it != m_peers.end())
			{
				Msg("[coop] '%s' (id=%u) left", it->second.name.c_str(), id);
				m_peers.erase(it);
			}
			break;
		}
		default:
			Msg("! [coop] unknown message type %u", type);
		}
	}

	void CClient::send_actor_state()
	{
		// g_actor, not Actor(): Actor() goes through Level().game, which is null while a save is loading
		if (!g_pGameLevel || !g_actor)
			return;

		NET_Packet P;
		P.w_begin(M_ACTOR_STATE);
		P.w_stringZ(Level().name());
		P.w_vec3(g_actor->Position());
		P.w_float(Device.vCameraDirection.getH()); // where the player looks, as the actor's own PDA arrow does
		send(P);
	}

	void CClient::OnFrame()
	{
		if (m_state == eFailed)
		{
			Msg("! [coop] disconnected: %s", m_error.c_str());
			Device.seqFrame.Remove(this);
			close();
			m_state = eIdle;
			m_welcomed = false;
			m_peers.clear();
			clear_map_markers();
			return;
		}

		if (m_state != eConnected)
			return;

		if (!m_hello_sent)
		{
			NET_Packet P;
			P.w_begin(M_HELLO);
			P.w_u16(PROTOCOL_VERSION);
			P.w_stringZ(m_name.c_str());
			send(P);
			m_hello_sent = true;
		}

		std::deque<xr_vector<u8>> inbox;
		{
			std::lock_guard<std::mutex> lock(m_inbox_lock);
			inbox.swap(m_inbox);
		}
		for (const xr_vector<u8>& msg : inbox)
		{
			NET_Packet P;
			P.construct(msg.data(), (u32)msg.size());
			handle(P);
		}
		update_map_markers();

		if (!m_welcomed)
			return;

		const u32 now = Device.dwTimeContinual;
		if (now - m_last_ping >= PING_INTERVAL_MS)
		{
			m_last_ping = now;
			NET_Packet P;
			P.w_begin(M_PING);
			P.w_u32(now);
			send(P);
		}
		if (now - m_last_actor_state >= ACTOR_STATE_INTERVAL_MS)
		{
			m_last_actor_state = now;
			send_actor_state();
		}
	}

	bool connect(LPCSTR host, u16 port, LPCSTR name)
	{
		if (g_client.busy())
		{
			Msg("! [coop] already connected or connecting, use coop_disconnect first");
			return false;
		}
		return g_client.start(host, port, name);
	}

	void disconnect()
	{
		g_client.stop();
		Msg("[coop] disconnected");
	}

	void print_status()
	{
		g_client.status();
	}

	bool is_connected() { return g_client.welcomed(); }
	void send(NET_Packet& P) { g_client.send(P); }
	u32 my_id() { return g_client.id(); }
	const peers_t& peers() { return g_client.peers(); }
}
