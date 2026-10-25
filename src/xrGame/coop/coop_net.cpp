#include "stdafx.h"
#include "coop_net.h"
#include "coop_map.h"
#include "coop_world.h"
#include "coop_ids.h"
#include "coop_shadow.h"
#include "coop_save.h"
#include "coop_progress.h"
#include "coop_puppet.h"
#include "coop_npc.h"
#include "coop_combat.h"
#include "coop_projectiles.h"
#include "ai_space.h"
#include "script_engine.h"
#include "Level.h"
#include "Actor.h"

#include <winsock2.h>
#include <ws2tcpip.h>
#include <thread>
#include <mutex>
#include <atomic>
#include <deque>
#include <functional>

#pragma comment(lib, "ws2_32.lib")

namespace coop
{
	const u32 PING_INTERVAL_MS = 1000;
	const u32 LOG_FLUSH_INTERVAL_MS = 5000; // the log is kept in memory and written out on exit or "flush"
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
		u32 master() const { return m_master_id; }
		u32 rtt() const { return m_rtt; }
		const xr_string& refusal() const { return m_refusal; }
		const xr_string& name() const { return m_name; }
		const peers_t& peers() const { return m_peers; }
		void send(NET_Packet& P);
		bool wait_for(const std::function<bool()>& done, u32 timeout_ms, std::initializer_list<u16> types);

		virtual void _BCL OnFrame();

	private:
		void worker();
		void close();
		bool recv_all(void* dst, u32 size);
		void handle(NET_Packet& P);
		void send_hello();
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
		xr_string m_refusal;

		u32 m_client_id = 0;
		u32 m_master_id = 0; // 0: not known yet, ids start at 1
		u32 m_last_ping = 0;
		u32 m_last_log_flush = 0;
		u32 m_last_actor_state = 0;
		u32 m_rtt = 0;

		peers_t m_peers;
		xr_set<u32> m_left; // client ids are never reused

	public:
		xr_vector<xr_vector<xr_string>> m_groups; // as the server has them
	};

	static CClient g_client;

	int debug_mode = 0;

	// coop_debug: how many messages of each type went each way, told every DEBUG_TRAFFIC_MS
	static const u32 DEBUG_TRAFFIC_MS = 5000;
	static const u16 MAX_TYPES = 64;
	static u32 g_sent[MAX_TYPES], g_received[MAX_TYPES];
	static u32 g_last_traffic = 0;

	static void count(u32* counts, u16 type)
	{
		if (debug_mode && type < MAX_TYPES)
			++counts[type];
	}

	static void debug_traffic()
	{
		if (!debug_mode || Device.dwTimeContinual - g_last_traffic < DEBUG_TRAFFIC_MS)
			return;
		g_last_traffic = Device.dwTimeContinual;
		xr_string sent, received;
		for (u16 type = 0; type < MAX_TYPES; ++type)
		{
			string32 one;
			if (g_sent[type])
			{
				xr_sprintf(one, " %u:%u", type, g_sent[type]);
				sent += one;
			}
			if (g_received[type])
			{
				xr_sprintf(one, " %u:%u", type, g_received[type]);
				received += one;
			}
			g_sent[type] = g_received[type] = 0;
		}
		Msg("[coop dbg] messages in %u s (type:count, coop_net.h): sent%s | received%s", DEBUG_TRAFFIC_MS / 1000,
		    sent.empty() ? " none" : sent.c_str(), received.empty() ? " none" : received.c_str());
	}

	// another client's Lua state change: handed to _G.coop_on_event(name, sender_name, payload)
	static void on_script_event(NET_Packet& P)
	{
		const u32 sender = P.r_u32();
		xr_string name, payload;
		P.r_stringZ(name);
		P.r_stringZ(payload);

		::luabind::functor<void> handler;
		if (!ai().script_engine().functor("_G.coop_on_event", handler))
			return;
		auto peer = g_client.peers().find(sender);
		handler(name.c_str(), peer != g_client.peers().end() ? peer->second.name.c_str() : "", payload.c_str());
	}

	// _G.<name>(args...) when Lua has it, in a level only
	template <typename... Args>
	static void call_lua(LPCSTR name, Args... args)
	{
		::luabind::functor<void> handler;
		if (g_pGameLevel && ai().script_engine().functor(name, handler))
			handler(args...);
	}

	// a peer showed up in the world (its first state) or left: _G.coop_on_peer(name, joined), in a level only
	static void notify_peer(const xr_string& name, bool joined)
	{
		::luabind::functor<void> handler;
		if (g_pGameLevel && ai().script_engine().functor("_G.coop_on_peer", handler))
			handler(name.c_str(), joined);
	}

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
		m_refusal.clear();
		m_hello_sent = false;
		m_welcomed = false;
		m_client_id = 0;
		m_master_id = 0;
		m_rtt = 0;
		m_inbox.clear();
		m_peers.clear();
		m_left.clear();
		m_groups.clear();

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
		FlushLog(); // the log is flushed from OnFrame, which ends here
		Device.seqFrame.Remove(this);
		m_state = eIdle;
		m_welcomed = false;
		m_peers.clear();
		clear_map_markers();
		clear_puppets();
		clear_npc_sync();
		clear_proxies();
		clear_grudges();
		clear_projectiles();
		reset_id_blocks();
		reset_world_sync();
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
			print_id_status();
			print_shadow_status();
			print_world_status();
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
		count(g_sent, *(const u16*)P.B.data);

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
		count(g_received, type);

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
		case M_REFUSED:
		{
			const u8 reason = P.r_u8();
			const u16 value = P.r_u16();
			m_refusal = reason == 0 ? "full" : "version";
			if (reason == 0)
				Msg("! [coop] the server is full: %u players at most", value);
			else
				Msg("! [coop] the server speaks protocol %u, this game %u", value, PROTOCOL_VERSION);
			break;
		}
		case M_PEER_STATE:
		{
			u32 id = P.r_u32();
			auto [it, inserted] = m_peers.try_emplace(id);
			SPeer& peer = it->second;
			P.r_stringZ(peer.name);
			P.r_stringZ(peer.level);
			P.r_vec3(peer.position);
			P.r_float(peer.yaw);
			if (P.r_elapsed())
			{
				read_look(P, peer.look);
				peer.has_look = true;
			}
			peer.last_update = Device.dwTimeContinual;
			if (inserted)
			{
				Msg("[coop] '%s' (id=%u) is on %s", peer.name.c_str(), id, peer.level.c_str());
				notify_peer(peer.name, true);
			}
			break;
		}
		case M_ID_BLOCK_GRANT:
			on_id_block_granted(P);
			break;
		case M_ITEM_PARENT:
			apply_item_parent(P);
			break;
		case M_OBJECT_RELEASE:
			apply_object_release(P);
			break;
		case M_OBJECT_SPAWN:
			apply_object_spawn(P);
			break;
		case M_ENTITY_DEATH:
			apply_entity_death(P);
			break;
		case M_ROLES:
		{
			const u32 master = P.r_u32();
			if (master != m_master_id)
			{
				auto peer = m_peers.find(master);
				Msg("[coop] sim master: %s", master == m_client_id ? "this client" :
				    peer != m_peers.end() ? peer->second.name.c_str() : "another client");
				m_master_id = master;
			}
			break;
		}
		case M_SCRIPT_EVENT:
			on_script_event(P);
			break;
		case M_WORLD_INFO:
			on_world_info(P);
			break;
		case M_WORLD_CHUNK:
			on_world_chunk(P);
			break;
		case M_WORLD_DONE:
			on_world_done(P);
			break;
		case M_CHARACTER:
			on_character(P);
			break;
		case M_SETTINGS:
			on_settings(P);
			break;
		case M_SAVE_NOW:
			on_save_now(P);
			break;
		case M_SAVES:
			on_saves(P);
			break;
		case M_ROLLBACK_VOTE:
			on_rollback_vote(P);
			break;
		case M_ROLLBACK_RESULT:
			on_rollback_result(P);
			break;
		case M_WORLD_RELOAD:
			on_world_reload();
			break;
		case M_PAUSE_VOTE:
			on_pause_vote(P);
			break;
		case M_PAUSE_RESULT:
			on_pause_result(P);
			break;
		case M_PAUSED:
			on_paused(P);
			break;
		case M_PROGRESS_REQUEST:
			send_progress();
			break;
		case M_PROGRESS:
			on_progress_chunk(P);
			break;
		case M_ACTOR_ACTION:
		{
			const u32 sender = P.r_u32();
			on_peer_action(sender, P);
			break;
		}
		case M_NPC_STATES:
		{
			const u32 sender = P.r_u32();
			on_npc_states(sender, P);
			break;
		}
		case M_COOP_HIT:
		{
			const u32 sender = P.r_u32();
			on_coop_hit(sender, P);
			break;
		}
		case M_GROUPS:
		{
			m_groups.clear();
			for (u8 count = P.r_u8(); count; --count)
			{
				xr_vector<xr_string>& group = m_groups.emplace_back();
				for (u8 size = P.r_u8(); size; --size)
					P.r_stringZ(group.emplace_back());
			}
			call_lua("_G.coop_on_groups");
			break;
		}
		case M_GROUP_INVITE:
		{
			const u32 inviter = P.r_u32();
			xr_string name;
			P.r_stringZ(name);
			const bool pda = P.r_elapsed() && P.r_u8() == 1;
			Msg("[coop] '%s' invites us to a group%s", name.c_str(), pda ? " (from the PDA)" : "");
			call_lua("_G.coop_on_group_invite", name.c_str(), inviter, pda);
			break;
		}
		case M_GROUP_NOTE:
		{
			const u8 note = P.r_u8();
			xr_string name;
			P.r_stringZ(name);
			call_lua("_G.coop_on_group_note", note, name.c_str());
			break;
		}
		case M_PEER_LEFT:
		{
			u32 id = P.r_u32();
			auto it = m_peers.find(id);
			if (it != m_peers.end())
			{
				Msg("[coop] '%s' (id=%u) left", it->second.name.c_str(), id);
				notify_peer(it->second.name, false);
				m_peers.erase(it);
			}
			m_left.insert(id);
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
		write_look(P);
		send(P);
	}

	void CClient::send_hello()
	{
		NET_Packet P;
		P.w_begin(M_HELLO);
		P.w_u16(PROTOCOL_VERSION);
		P.w_stringZ(m_name.c_str());
		send(P);
		m_hello_sent = true;
	}

	// Level loading runs without frames, so OnFrame can't talk to the server then. This does it in place:
	// handles only the given message types (others stay queued for OnFrame) until done() or timeout.
	bool CClient::wait_for(const std::function<bool()>& done, u32 timeout_ms, std::initializer_list<u16> types)
	{
		const u32 start = GetTickCount(); // Device time doesn't advance while loading
		while (true)
		{
			if (m_state == eConnected)
			{
				if (!m_hello_sent)
					send_hello();

				std::deque<xr_vector<u8>> matched;
				{
					std::lock_guard<std::mutex> lock(m_inbox_lock);
					for (auto it = m_inbox.begin(); it != m_inbox.end();)
					{
						const u16 type = *(const u16*)it->data();
						if (std::find(types.begin(), types.end(), type) != types.end())
						{
							matched.push_back(std::move(*it));
							it = m_inbox.erase(it);
						}
						else
							++it;
					}
				}
				for (const xr_vector<u8>& msg : matched)
				{
					NET_Packet P;
					P.construct(msg.data(), (u32)msg.size());
					handle(P);
				}
			}
			else if (m_state != eConnecting)
				return false;

			if (done())
				return true;
			if (GetTickCount() - start >= timeout_ms)
				return false;
			Sleep(1);
		}
	}

	void CClient::OnFrame()
	{
		// co-op sessions are debugged from the log while the games run
		if (Device.dwTimeContinual - m_last_log_flush >= LOG_FLUSH_INTERVAL_MS)
		{
			m_last_log_flush = Device.dwTimeContinual;
			FlushLog();
		}

		if (m_state == eFailed)
		{
			// a server turning us away says why just before it closes: that is still unread here
			{
				std::lock_guard<std::mutex> lock(m_inbox_lock);
				for (xr_vector<u8>& msg : m_inbox)
					if (msg.size() >= sizeof(u16) && *(const u16*)msg.data() == M_REFUSED)
					{
						NET_Packet P;
						P.construct(msg.data(), (u32)msg.size());
						handle(P);
					}
				m_inbox.clear();
			}
			Msg("! [coop] disconnected: %s", m_error.c_str());
			FlushLog(); // the log is flushed from OnFrame, which ends here
			Device.seqFrame.Remove(this);
			close();
			m_state = eIdle;
			m_welcomed = false;
			m_peers.clear();
			clear_map_markers();
			clear_puppets();
			clear_npc_sync();
			clear_proxies();
			clear_grudges();
			clear_projectiles();
			reset_id_blocks();
			reset_world_sync();
			return;
		}

		if (m_state != eConnected)
			return;

		if (!m_hello_sent)
			send_hello();

		std::deque<xr_vector<u8>> inbox;
		{
			std::lock_guard<std::mutex> lock(m_inbox_lock);
			inbox.swap(m_inbox);
		}
		// World changes that arrive while our level loads wait for it, in order: the other world kept
		// going meanwhile (a trader restocked on its first update...), and dropping them loses that.
		// Those relayed with the sender's id also wait until we know the sender (its first PEER_STATE),
		// since "the sender's actor" is their shadow, found by name. Once one waits, all later world
		// changes wait too, so they stay in order.
		const bool ready = world_ready();
		bool hold = !ready;
		std::deque<xr_vector<u8>> deferred;
		for (xr_vector<u8>& msg : inbox)
		{
			const u16 type = *(const u16*)msg.data();
			const bool from_sender = type == M_ITEM_PARENT || type == M_OBJECT_RELEASE || type == M_OBJECT_SPAWN ||
				type == M_SCRIPT_EVENT;
			const bool world_change = from_sender || type == M_ENTITY_DEATH;
			if (from_sender && msg.size() >= sizeof(u16) + sizeof(u32))
			{
				const u32 sender = *(const u32*)(msg.data() + sizeof(u16));
				if (m_left.count(sender))
					continue; // that player is gone: no shadow to apply it to
				if (!m_peers.count(sender))
					hold = true;
			}
			if (world_change && hold)
			{
				deferred.push_back(std::move(msg));
				continue;
			}
			NET_Packet P;
			P.construct(msg.data(), (u32)msg.size());
			handle(P);
		}
		if (!deferred.empty())
		{
			std::lock_guard<std::mutex> lock(m_inbox_lock);
			m_inbox.insert(m_inbox.begin(), std::make_move_iterator(deferred.begin()),
			               std::make_move_iterator(deferred.end()));
		}
		update_map_markers();
		update_puppets();
		update_npc_sync();
		update_combat();
		update_projectiles();
		update_id_blocks();
		update_shadows();
		update_bodies();
		update_releases();
		update_world_sync();
		debug_traffic();

		if (!m_welcomed)
			return;

		const u32 now = Device.dwTimeContinual;
		if (now - m_last_ping >= PING_INTERVAL_MS)
		{
			m_last_ping = now;
			NET_Packet P;
			P.w_begin(M_PING);
			P.w_u32(now);
			P.w_u32(m_rtt);
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
	bool is_link_up() { return g_client.busy(); }
	bool wait_for_messages(const std::function<bool()>& done, u32 timeout_ms, std::initializer_list<u16> types)
	{
		return g_client.wait_for(done, timeout_ms, types);
	}
	void send(NET_Packet& P) { g_client.send(P); }
	u32 my_id() { return g_client.id(); }
	u32 ping_ms() { return g_client.rtt(); }
	LPCSTR refusal() { return g_client.refusal().c_str(); }
	const xr_string& my_name() { return g_client.name(); }

	bool is_sim_master()
	{
		return !is_connected() || g_client.master() == g_client.id();
	}

	bool is_authority(const shared_str& level_name)
	{
		if (!is_connected())
			return true;

		u32 owner = u32(-1);
		if (g_pGameLevel && Level().name() == level_name)
			owner = g_client.id();
		for (const auto& [id, peer] : g_client.peers())
			if (peer.level == level_name && id < owner)
				owner = id;
		if (owner == u32(-1))
			owner = g_client.master();
		return owner == g_client.id();
	}
	const peers_t& peers() { return g_client.peers(); }

	const xr_vector<xr_string>* group_of(const xr_string& name)
	{
		for (const auto& group : g_client.m_groups)
			if (std::find(group.begin(), group.end(), name) != group.end())
				return &group;
		return nullptr;
	}

	static const xr_string* name_of(u32 id)
	{
		if (id == my_id())
			return &my_name();
		auto peer = peers().find(id);
		return peer != peers().end() ? &peer->second.name : nullptr;
	}

	bool same_group(u32 a, u32 b)
	{
		const xr_string* name_a = name_of(a);
		const xr_string* name_b = name_of(b);
		const xr_vector<xr_string>* group = name_a && name_b ? group_of(*name_a) : nullptr;
		return group && std::find(group->begin(), group->end(), *name_b) != group->end();
	}

	void group_request(EGroupAction action, u32 peer, LPCSTR name, bool pda)
	{
		NET_Packet P;
		P.w_begin(M_GROUP);
		P.w_u8(action);
		if (action == eGroupKick)
			P.w_stringZ(name);
		else if (action != eGroupLeave)
			P.w_u32(peer);
		if (action == eGroupInvite)
			P.w_u8(pda ? 1 : 0);
		send(P);
	}
}
