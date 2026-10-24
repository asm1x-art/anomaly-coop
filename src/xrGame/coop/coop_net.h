#pragma once

// Co-op network channel: TCP connection to the coop world server.
// Wire format: u32 size (of type + payload) | u16 type | payload, little-endian.

namespace coop
{
	enum EMessage : u16
	{
		M_HELLO = 1,   // c->s: u16 protocol version, stringZ name
		M_WELCOME = 2, // s->c: u32 client id
		M_PING = 3,    // c->s: u32 client time (ms)
		M_PONG = 4,    // s->c: u32 echoed client time (ms)
	};

	const u16 PROTOCOL_VERSION = 1;

	bool connect(LPCSTR host, u16 port, LPCSTR name);
	void disconnect();
	void print_status();
}
