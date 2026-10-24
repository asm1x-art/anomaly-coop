#include "stdafx.h"
#include "coop_map.h"
#include "coop_net.h"
#include "Level.h"
#include "Actor.h"
#include "map_location.h"
#include "map_location_defs.h"
#include "map_spot.h"
#include "map_manager.h"
#include "ai_space.h"
#include "game_graph.h"
#include "xrServer_Objects_ALife.h"

namespace coop
{
	// Like the actor's own pair (actor_location + actor_location_p): a figure and a view-direction arrow.
	// Both spot types are defined in gamedata/scripts/modxml_coop.script.
	enum EMarker : u8
	{
		eFigure,
		eArrow,
		eMarkerCount,
	};
	static LPCSTR PEER_SPOT_TYPES[eMarkerCount] = {"coop_peer_location", "coop_peer_location_p"};
	static const u16 NO_OBJECT_ID = u16(-1);
	static const float REGRAPH_DISTANCE = 10.f;

	u32 peer_color = color_rgba(90, 200, 255, 255);

	class CPeerLocation;
	using marker_key = std::pair<u32, EMarker>; // peer id, marker kind
	static xr_map<marker_key, CPeerLocation*> g_markers;

	// A map spot that isn't attached to a real object. CMapLocation reads level name, position
	// and visibility from its owner server object, so we give it a private proxy that is never
	// registered in A-Life and move the proxy around by the peer's reported state.
	class CPeerLocation : public CMapLocation
	{
	public:
		CPeerLocation(const marker_key& key) : CMapLocation(PEER_SPOT_TYPES[key.second], NO_OBJECT_ID), m_key(key)
		{
			m_proxy = xr_new<CSE_ALifeDynamicObject>("actor");
			m_owner_se_object = m_proxy;
		}

		virtual void destroy()
		{
			// also reached when the level unloads and CMapManager deletes its locations
			auto it = g_markers.find(m_key);
			if (it != g_markers.end() && it->second == this)
				g_markers.erase(it);
			m_owner_se_object = nullptr;
			xr_delete(m_proxy);
			CMapLocation::destroy();
		}

		void set(const SPeer& peer)
		{
			if (m_key.second == eFigure && m_hint != peer.name.c_str())
			{
				m_hint = peer.name.c_str();
				SetHint(m_hint);
			}

			if (m_level_spot)
				m_level_spot->SetTextureColor(peer_color);
			if (m_minimap_spot)
				m_minimap_spot->SetTextureColor(peer_color);

			m_yaw = peer.yaw;
			m_proxy->o_Position = peer.position;
			if (peer.level != m_graph_level || m_graph_position.distance_to(peer.position) > REGRAPH_DISTANCE)
			{
				m_proxy->m_tGraphID = nearest_vertex(peer.level, peer.position);
				m_graph_level = peer.level;
				m_graph_position = peer.position;
			}
		}

		bool has_vertex() const { return m_proxy->m_tGraphID != GameGraph::_GRAPH_ID(-1); }

		// the base version asks the level object for its direction, and we have none
		virtual const Fvector2& CalcDirection()
		{
			Fvector direction;
			direction.setHP(m_yaw, 0.f);
			m_cached.m_Direction.set(direction.x, direction.z);
			return m_cached.m_Direction;
		}

	private:
		static GameGraph::_GRAPH_ID nearest_vertex(const shared_str& level_name, const Fvector& position)
		{
			const CGameGraph& graph = ai().game_graph();

			GameGraph::_LEVEL_ID level_id = GameGraph::_LEVEL_ID(-1);
			for (const auto& [id, level] : graph.header().levels())
				if (level.name() == level_name)
					level_id = id;
			if (level_id == GameGraph::_LEVEL_ID(-1))
				return GameGraph::_GRAPH_ID(-1);

			GameGraph::_GRAPH_ID best = GameGraph::_GRAPH_ID(-1);
			float best_distance = flt_max;
			for (GameGraph::_GRAPH_ID i = 0; i < graph.header().vertex_count(); ++i)
			{
				const CGameGraph::CVertex* vertex = graph.vertex(i);
				if (vertex->level_id() != level_id)
					continue;
				float distance = vertex->level_point().distance_to_sqr(position);
				if (distance < best_distance)
				{
					best_distance = distance;
					best = i;
				}
			}
			return best;
		}

		marker_key m_key;
		CSE_ALifeDynamicObject* m_proxy;
		float m_yaw = 0.f;
		shared_str m_hint;
		shared_str m_graph_level;
		Fvector m_graph_position = {flt_max, flt_max, flt_max};
	};

	static void add_marker(const marker_key& key, CPeerLocation* location)
	{
		// same bookkeeping as CMapManager::AddMapLocation, minus the script callbacks
		Level().MapManager().Locations().push_back(SLocationKey(PEER_SPOT_TYPES[key.second], NO_OBJECT_ID));
		Level().MapManager().Locations().back().location = location;
		g_markers[key] = location;
	}

	static void remove_marker(xr_map<marker_key, CPeerLocation*>::iterator it)
	{
		// RemoveMapLocation destroys the location next frame, so forget it right away
		CPeerLocation* location = it->second;
		g_markers.erase(it);
		Level().MapManager().RemoveMapLocation(location);
	}

	void update_map_markers()
	{
		// g_actor, not Actor(): Actor() goes through Level().game, which is null while a save is loading
		if (!g_pGameLevel || !g_actor || !ai().get_game_graph())
			return;

		const peers_t& list = peers();

		for (auto it = g_markers.begin(); it != g_markers.end();)
		{
			auto next = std::next(it);
			if (list.find(it->first.first) == list.end())
				remove_marker(it);
			it = next;
		}

		for (const auto& [id, peer] : list)
		{
			for (u8 kind = 0; kind < eMarkerCount; ++kind)
			{
				const marker_key key(id, EMarker(kind));
				auto it = g_markers.find(key);
				if (it != g_markers.end())
				{
					it->second->set(peer);
					continue;
				}

				CPeerLocation* location = xr_new<CPeerLocation>(key);
				location->set(peer);
				if (!location->has_vertex())
				{
					// unknown level name: nothing sensible to draw
					location->destroy();
					xr_delete(location);
					continue;
				}
				add_marker(key, location);
			}
		}
	}

	void clear_map_markers()
	{
		if (!g_pGameLevel)
		{
			g_markers.clear();
			return;
		}
		while (!g_markers.empty())
			remove_marker(g_markers.begin());
	}
}
