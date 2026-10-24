#pragma once

// Co-op network channel: TCP connection to the coop world server.
// Wire format: u32 size | NET_Packet bytes (u16 type | payload), little-endian.

#include <functional>

struct lua_State;

namespace coop
{
	enum EMessage : u16
	{
		M_HELLO = 1,       // c->s: u16 protocol version, stringZ name
		M_WELCOME = 2,     // s->c: u32 client id
		M_PING = 3,        // c->s: u32 client time (ms)
		M_PONG = 4,        // s->c: u32 echoed client time (ms)
		M_ACTOR_STATE = 5, // c->s: stringZ level, vec3 position, float yaw
		M_PEER_STATE = 6,  // s->c: u32 id, stringZ name, then M_ACTOR_STATE payload
		M_PEER_LEFT = 7,   // s->c: u32 id
		M_ENTITY_DEATH = 8, // c->s->others: u16 object id, stringZ section, u16 killer id
		M_ID_BLOCK_REQUEST = 9, // c->s: u16 free ids per id block (all blocks, as the client sees them)
		M_ID_BLOCK_GRANT = 10,  // s->c: u16 block leased to this player, u16(-1) when none are left
		// relayed to the others with the sender's client id in front (s->c: u32 sender, then the payload)
		M_ITEM_PARENT = 11,     // c->s: u16 item, stringZ section, u8 place, place data (coop_world.cpp)
		M_OBJECT_RELEASE = 12,  // c->s: u16 object, stringZ section
		M_OBJECT_SPAWN = 13,    // c->s: u16 size, the engine's M_SPAWN packet (CSE_Abstract::Spawn_Write)
	};

	const u16 PROTOCOL_VERSION = 6;

	struct SPeer
	{
		xr_string name;
		shared_str level;
		Fvector position;
		float yaw;
		u32 last_update; // Device.dwTimeContinual
	};

	using peers_t = xr_map<u32, SPeer>;

	bool connect(LPCSTR host, u16 port, LPCSTR name);
	void disconnect();
	void print_status();

	bool is_connected();
	bool is_link_up(); // connecting or connected, welcomed or not
	void send(NET_Packet& P); // dropped unless connected

	// Exchange messages right now instead of on the next frame (frames don't run while a level loads).
	// Only the given message types are handled, the rest stays queued; false on timeout or lost link.
	bool wait_for_messages(const std::function<bool()>& done, u32 timeout_ms, std::initializer_list<u16> types);
	u32 my_id();
	const peers_t& peers();

	void script_register(lua_State* L);
}
