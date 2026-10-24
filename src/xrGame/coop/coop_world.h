#pragma once

// World state replication between co-op clients.
// Every client runs a full local A-Life; changes are mirrored by object id,
// so all clients must start from the same world (same save).

class CSE_ALifeCreatureAbstract;
class CSE_Abstract;
class NET_Packet;

namespace coop
{
	// called from CSE_ALifeCreatureAbstract::on_death, online and offline deaths alike
	void on_creature_death(CSE_ALifeCreatureAbstract* victim, CSE_Abstract* killer);

	// M_ENTITY_DEATH from another client
	void apply_entity_death(NET_Packet& P);
}
