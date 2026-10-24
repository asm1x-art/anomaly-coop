#include "stdafx.h"
#include "coop_net.h"

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
	const u32 MAX_MESSAGE_SIZE = 1024 * 1024;

	struct SMessage
	{
		u16 type;
		xr_vector<u8> data;
	};

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

		virtual void _BCL OnFrame();

	private:
		void worker();
		void close();
		bool recv_all(void* dst, u32 size);
		void send(u16 type, const void* payload, u32 size);
		void handle(const SMessage& msg);

		SOCKET m_socket = INVALID_SOCKET;
		std::thread m_thread;
		std::atomic<int> m_state = eIdle;
		bool m_hello_sent = false;
		bool m_welcomed = false;

		std::mutex m_inbox_lock;
		std::deque<SMessage> m_inbox;

		xr_string m_host;
		u16 m_port = 0;
		xr_string m_name;
		xr_string m_error;

		u32 m_client_id = 0;
		u32 m_last_ping = 0;
		u32 m_rtt = 0;
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
	}

	void CClient::status() const
	{
		switch (m_state)
		{
		case eIdle: Msg("[coop] status: idle"); break;
		case eConnecting: Msg("[coop] status: connecting to %s:%u", m_host.c_str(), m_port); break;
		case eConnected:
			Msg("[coop] status: connected to %s:%u, id=%u, rtt=%u ms", m_host.c_str(), m_port, m_client_id, m_rtt);
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
			if (size < sizeof(u16) || size > MAX_MESSAGE_SIZE)
			{
				m_error = "bad message size";
				break;
			}

			SMessage msg;
			if (!recv_all(&msg.type, sizeof(msg.type)))
				break;
			msg.data.resize(size - sizeof(u16));
			if (!msg.data.empty() && !recv_all(msg.data.data(), (u32)msg.data.size()))
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

	void CClient::send(u16 type, const void* payload, u32 size)
	{
		if (m_state != eConnected)
			return;

		xr_vector<u8> buf(sizeof(u32) + sizeof(u16) + size);
		*(u32*)buf.data() = sizeof(u16) + size;
		*(u16*)(buf.data() + sizeof(u32)) = type;
		if (size)
			memcpy(buf.data() + sizeof(u32) + sizeof(u16), payload, size);

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

	void CClient::handle(const SMessage& msg)
	{
		switch (msg.type)
		{
		case M_WELCOME:
			if (msg.data.size() >= sizeof(u32))
			{
				m_client_id = *(const u32*)msg.data.data();
				m_welcomed = true;
				Msg("[coop] connected to %s:%u, id=%u", m_host.c_str(), m_port, m_client_id);
			}
			break;
		case M_PONG:
			if (msg.data.size() >= sizeof(u32))
				m_rtt = Device.dwTimeContinual - *(const u32*)msg.data.data();
			break;
		default:
			Msg("! [coop] unknown message type %u", msg.type);
		}
	}

	void CClient::OnFrame()
	{
		if (m_state == eFailed)
		{
			Msg("! [coop] disconnected: %s", m_error.c_str());
			Device.seqFrame.Remove(this);
			close();
			m_state = eIdle;
			return;
		}

		if (m_state != eConnected)
			return;

		if (!m_hello_sent)
		{
			// first frame after connect: introduce ourselves
			xr_vector<u8> hello(sizeof(u16) + m_name.size() + 1);
			*(u16*)hello.data() = PROTOCOL_VERSION;
			memcpy(hello.data() + sizeof(u16), m_name.c_str(), m_name.size() + 1);
			send(M_HELLO, hello.data(), (u32)hello.size());
			m_hello_sent = true;
		}

		std::deque<SMessage> inbox;
		{
			std::lock_guard<std::mutex> lock(m_inbox_lock);
			inbox.swap(m_inbox);
		}
		for (const SMessage& msg : inbox)
			handle(msg);

		if (m_welcomed && Device.dwTimeContinual - m_last_ping >= PING_INTERVAL_MS)
		{
			m_last_ping = Device.dwTimeContinual;
			send(M_PING, &m_last_ping, sizeof(m_last_ping));
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
}
