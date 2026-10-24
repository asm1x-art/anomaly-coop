#pragma once

// Object id ownership. The server leases whole id generator blocks (256 ids each) to clients,
// and a client creates new objects only with ids from its own blocks, so two clients can never
// give the same id to different objects, even when their worlds have drifted apart.

class xrServer;
class NET_Packet;

namespace coop
{
	// xrServer::PerformIDgen asks here first for a brand new id; u16(-1) means "use the normal generator"
	u16 allocate_id(xrServer& server);

	void on_id_block_granted(NET_Packet& P);
	void update_id_blocks(); // per frame: keeps a reserve of free ids by asking for more blocks
	void reset_id_blocks();  // on disconnect
	void print_id_status();
}
