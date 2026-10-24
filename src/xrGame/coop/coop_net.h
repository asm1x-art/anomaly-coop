#pragma once

// Co-op network channel: TCP connection to the coop world server.
// Wire format: u32 size | NET_Packet bytes (u16 type | payload), little-endian.

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
	};

	const u16 PROTOCOL_VERSION = 3;

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
	void send(NET_Packet& P); // dropped unless connected
	u32 my_id();
	const peers_t& peers();

	void script_register(lua_State* L);
}
