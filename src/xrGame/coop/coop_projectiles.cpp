#include "stdafx.h"
#include "coop_projectiles.h"
#include "coop_net.h"
#include "coop_combat.h"
#include "coop_puppet.h"
#include "coop_world.h"
#include "Level.h"
#include "Level_Bullet_Manager.h"
#include "Actor.h"
#include "ActorEffector.h"
#include "CameraEffector.h"
#include "Explosive.h"
#include "ShootingObject.h"
#include "ai/stalker/ai_stalker.h"
#include "ParticlesObject.h"
#include "../xrEngine/GameMtlLib.h"
#include "HudSound.h"
#include "ai_sounds.h"
#include "WeaponAmmo.h"
#include "wallmark_manager.h"
#include "../xrEngine/IRenderable.h"
#include "../xrcdb/ispatial.h"
#include "../Include/xrRender/Kinematics.h"

namespace coop
{
	static const u32 STREAM_INTERVAL_MS = 50;
	static const u32 MAX_FLIGHT_MS = 10000; // a bolt lies about long after it landed: not streamed for ever
	static const u32 LOST_MS = 1500;        // nothing heard of another game's flying thing this long: gone
	static const float FOLLOW_RATE = 25.f;
	static const float EFFECTOR_RADIUS = 30.f; // CExplosive's camera shake
	static const u16 NO_OBJECT = u16(-1);

	// another game's grenade or rocket in flight: its model where that game has it
	class CFlying : public IRenderable, public ISpatial
	{
	public:
		CFlying(const shared_str& section) : ISpatial(g_SpatialSpace)
		{
			renderable.visual = nullptr;
			renderable.xform.identity();
			spatial.type |= STYPE_RENDERABLE;
			if (pSettings->line_exist(section, "visual"))
				renderable.visual = ::Render->model_Create(pSettings->r_string(section, "visual"));
			// a rocket's smoke trail (CCustomRocket)
			LPCSTR trail = pSettings->line_exist(section, "engine_particles") ? "engine_particles" :
				pSettings->line_exist(section, "fly_particles") ? "fly_particles" : nullptr;
			if (trail)
				m_trail = CParticlesObject::Create(pSettings->r_string(section, trail), FALSE);
		}

		virtual ~CFlying()
		{
			spatial_unregister();
			if (m_trail)
			{
				m_trail->Stop();
				CParticlesObject::Destroy(m_trail);
			}
			if (renderable.visual)
				::Render->model_Delete(renderable.visual);
		}

		virtual IRenderable* dcast_Renderable() { return this; }
		virtual BOOL renderable_ShadowGenerate() { return TRUE; }
		virtual BOOL renderable_ShadowReceive() { return TRUE; }

		void set(const Fvector& position, const Fquaternion& rotation)
		{
			m_target = position;
			m_target_rotation = rotation;
			m_heard = Device.dwTimeContinual;
			if (!m_placed)
			{
				m_position = position;
				m_rotation = rotation;
				m_placed = true;
			}
		}

		void update()
		{
			const float k = _min(1.f, Device.fTimeDelta * FOLLOW_RATE);
			m_position.lerp(m_position, m_target, k);
			m_rotation.slerp(m_rotation, m_target_rotation, k);
			renderable.xform.rotation(m_rotation);
			renderable.xform.c.set(m_position);
			spatial.sphere.P.set(m_position);
			spatial.sphere.R = 0.5f;
			if (spatial.node_ptr)
				spatial_move();
			else
				spatial_register();
			if (m_trail)
			{
				m_trail->UpdateParent(renderable.xform, Fvector().set(0.f, 0.f, 0.f));
				if (!m_trail->IsPlaying())
					m_trail->Play(false);
			}
		}

		bool lost() const { return Device.dwTimeContinual - m_heard > LOST_MS; }

		virtual void renderable_Render()
		{
			if (!renderable.visual)
				return;
			if (IKinematics* K = renderable.visual->dcast_PKinematics())
			{
				K->CalculateBones_Invalidate();
				K->CalculateBones(TRUE);
			}
			::Render->set_Transform(&renderable.xform);
			::Render->add_Visual(renderable.visual);
		}

	private:
		bool m_placed = false;
		Fvector m_position = {0.f, 0.f, 0.f}, m_target = {0.f, 0.f, 0.f};
		Fquaternion m_rotation, m_target_rotation;
		u32 m_heard = 0;
		CParticlesObject* m_trail = nullptr;
	};

	// an explosion's light, put out when its time is up
	struct SFlash
	{
		ref_light light;
		float until;
	};

	static xr_map<u16, u32> g_flying;                          // ours in flight: id -> when it was launched
	static u32 g_last_stream = 0;
	static xr_map<std::pair<u32, u16>, CFlying*> g_projectiles; // theirs: (sender, its object id) -> model
	static xr_vector<SFlash> g_flashes;
	static xr_map<shared_str, HUD_SOUND_COLLECTION_LAYERED*> g_explode_sounds;
	static CWalmarkManager* g_wallmarks = nullptr;

	void on_projectile_launched(CGameObject& projectile, const CObject* thrower)
	{
		if (!is_connected() || !g_pGameLevel || !thrower)
			return;
		const bool ours = thrower == g_actor ||
			(smart_cast<const CAI_Stalker*>(thrower) && !is_proxy(thrower) && is_authority(Level().name()));
		if (ours)
			g_flying[projectile.ID()] = Device.dwTimeContinual;
	}

	void on_explode(CGameObject& explosive, const Fvector& position, const Fvector& direction, s32 seed)
	{
		g_flying.erase(explosive.ID());
		if (!is_connected() || !g_pGameLevel)
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eExplosion);
		P.w_u16(explosive.ID());
		P.w_stringZ(explosive.cNameSect());
		P.w_vec3(position);
		P.w_vec3(direction);
		P.w_s32(seed);
		send(P);
	}

	static bool on_our_level(u32 sender)
	{
		auto peer = peers().find(sender);
		return peer != peers().end() && peer->second.level == Level().name();
	}

	void play_projectile(u32 sender, NET_Packet& P)
	{
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);
		Fvector position;
		P.r_vec3(position);
		Fquaternion rotation;
		rotation.x = P.r_float();
		rotation.y = P.r_float();
		rotation.z = P.r_float();
		rotation.w = P.r_float();
		if (!world_ready() || !on_our_level(sender) || !pSettings->section_exist(section))
			return;
		CFlying*& flying = g_projectiles[{sender, id}];
		if (!flying)
			flying = xr_new<CFlying>(section);
		flying->set(position, rotation);
	}

	// what CExplosive::Explode shows, for an explosion of something we don't have here
	static void blank_explosion(LPCSTR section, const Fvector& position, const Fvector& direction, s32 seed)
	{
		Fmatrix where;
		where.identity();
		where.j.set(direction);
		Fvector::generate_orthonormal_basis(where.j, where.i, where.k);
		where.c.set(position);
		if (pSettings->line_exist(section, "explode_particles"))
		{
			CParticlesObject* particles = CParticlesObject::Create(pSettings->r_string(section, "explode_particles"), TRUE);
			particles->UpdateParent(where, Fvector().set(0.f, 0.f, 0.f));
			particles->Play(false);
		}

		HUD_SOUND_COLLECTION_LAYERED*& sound = g_explode_sounds[section];
		if (!sound && pSettings->line_exist(section, "snd_explode"))
		{
			sound = xr_new<HUD_SOUND_COLLECTION_LAYERED>();
			sound->LoadSound(section, "snd_explode", "sndExplode", false, SOUND_TYPE_NO_SOUND);
		}
		if (sound)
			sound->PlaySound("sndExplode", position, nullptr, false, false, u8(-1));

		const float light_time = READ_IF_EXISTS(pSettings, r_float, section, "light_time", 0.f);
		if (light_time > 0.f)
		{
			Fcolor color;
			sscanf(pSettings->r_string(section, "light_color"), "%f,%f,%f", &color.r, &color.g, &color.b);
			SFlash flash;
			flash.light = ::Render->light_create();
			flash.light->set_shadow(true);
			flash.light->set_color(color.r, color.g, color.b);
			flash.light->set_range(pSettings->r_float(section, "light_range"));
			flash.light->set_position(position);
			flash.light->set_active(true);
			flash.until = Device.fTimeGlobal + light_time;
			g_flashes.push_back(flash);
		}

		if (!g_wallmarks)
		{
			g_wallmarks = xr_new<CWalmarkManager>();
			g_wallmarks->m_owner = nullptr;
		}
		g_wallmarks->PlaceWallmarks(position);

		// the same fragments, from the same seed (CExplosive::Explode)
		const int frags = READ_IF_EXISTS(pSettings, r_s32, section, "frags", 0);
		if (frags > 0)
		{
			CCartridge cartridge;
			cartridge.param_s.kDist = 1.f;
			cartridge.param_s.kHit = 1.f;
			cartridge.param_s.kImpulse = 1.f;
			cartridge.param_s.kAP = READ_IF_EXISTS(pSettings, r_float, section, "frags_ap", 1.0f);
			cartridge.param_s.kAirRes = READ_IF_EXISTS(pSettings, r_float, section, "frags_air_resistance", 1.0f);
			cartridge.param_s.fWallmarkSize = pSettings->r_float(section, "wm_size");
			cartridge.param_s.u8ColorID = READ_IF_EXISTS(pSettings, r_u8, section, "frags_tracer_color_ID", 0);
			cartridge.m_4to1_tracer = READ_IF_EXISTS(pSettings, r_bool, section, "frags_4to1_tracer", false);
			cartridge.bullet_material_idx = GMLib.GetMaterialIdx(WEAPON_MATERIAL_NAME);
			cartridge.m_flags.set(CCartridge::cfTracer, READ_IF_EXISTS(pSettings, r_bool, section, "frags_tracer", false));
			cartridge.m_flags.set(CCartridge::cfRicochet, READ_IF_EXISTS(pSettings, r_bool, section, "frags_allow_ricochet", true));
			cartridge.m_flags.set(CCartridge::cfMagneticBeam,
			                      READ_IF_EXISTS(pSettings, r_bool, section, "frags_magnetic_beam_shot", false));
			const float speed = pSettings->r_float(section, "fragment_speed");
			const float hit = pSettings->r_float(section, "frag_hit");
			const float impulse = pSettings->r_float(section, "frag_hit_impulse");
			const float radius = pSettings->r_float(section, "frags_r");
			const ALife::EHitType type = ALife::g_tfString2HitType(pSettings->r_string(section, "hit_type_frag"));
			CRandom rng(seed);
			for (int i = 0; i < frags; ++i)
			{
				Fvector frag;
				frag.random_dir(rng);
				frag.normalize();
				Level().BulletManager().AddBullet(position, frag, speed, hit, impulse, NO_OBJECT, NO_OBJECT, type, radius,
				                                  cartridge, cartridge.param_s.kAirRes, false, false, i + 1, seed + i + 1);
			}
		}

		if (g_actor)
		{
			const float distance = g_actor->Position().distance_to(position);
			LPCSTR effect = pSettings->line_exist(section, "explode_effector_sect_name") ?
				pSettings->r_string(section, "explode_effector_sect_name") :
				pSettings->r_string("explode_effector", "effect_sect_name");
			if (distance < EFFECTOR_RADIUS && xr_strcmp(effect, "$no_effector"))
				AddEffector(g_actor, effExplodeHit, effect, (EFFECTOR_RADIUS - distance) / EFFECTOR_RADIUS);
		}
	}

	void play_explosion(u32 sender, NET_Packet& P)
	{
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);
		Fvector position, direction;
		P.r_vec3(position);
		P.r_vec3(direction);
		const s32 seed = P.r_s32();

		auto flying = g_projectiles.find({sender, id});
		if (flying != g_projectiles.end())
		{
			xr_delete(flying->second);
			g_projectiles.erase(flying);
		}
		if (!world_ready() || !on_our_level(sender) || !pSettings->section_exist(section))
			return;

		// our copy of the very thing that blew up (a barrel), lying about: it blows up too, as a blank
		CGameObject* object = smart_cast<CGameObject*>(Level().Objects.net_Find(id));
		CExplosive* explosive = object ? smart_cast<CExplosive*>(object) : nullptr;
		if (explosive && !object->H_Parent() && object->cNameSect() == section &&
		    explosive->coop_blank_explode(position, direction, seed))
			return;
		blank_explosion(*section, position, direction, seed);
	}

	void update_projectiles()
	{
		if (!world_ready())
			return;

		for (auto it = g_flashes.begin(); it != g_flashes.end();)
		{
			if (Device.fTimeGlobal < it->until)
			{
				++it;
				continue;
			}
			it->light->set_active(false);
			it = g_flashes.erase(it);
		}

		for (auto it = g_projectiles.begin(); it != g_projectiles.end();)
		{
			if (it->second->lost())
			{
				xr_delete(it->second);
				it = g_projectiles.erase(it);
				continue;
			}
			it->second->update();
			++it;
		}

		if (g_flying.empty() || Device.dwTimeContinual - g_last_stream < STREAM_INTERVAL_MS)
			return;
		g_last_stream = Device.dwTimeContinual;
		for (auto it = g_flying.begin(); it != g_flying.end();)
		{
			CGameObject* object = smart_cast<CGameObject*>(Level().Objects.net_Find(it->first));
			CExplosive* explosive = object ? smart_cast<CExplosive*>(object) : nullptr;
			if (!object || object->getDestroy() || object->H_Parent() || (explosive && explosive->IsExploding()) ||
			    Device.dwTimeContinual - it->second > MAX_FLIGHT_MS)
			{
				it = g_flying.erase(it);
				continue;
			}
			Fquaternion rotation;
			rotation.set(object->XFORM());
			NET_Packet P;
			P.w_begin(M_ACTOR_ACTION);
			P.w_u8(eProjectile);
			P.w_u16(object->ID());
			P.w_stringZ(object->cNameSect());
			P.w_vec3(object->Position());
			P.w_float(rotation.x);
			P.w_float(rotation.y);
			P.w_float(rotation.z);
			P.w_float(rotation.w);
			send(P);
			++it;
		}
	}

	void clear_projectiles()
	{
		for (auto& [key, flying] : g_projectiles)
			xr_delete(flying);
		g_projectiles.clear();
		for (SFlash& flash : g_flashes)
			flash.light->set_active(false);
		g_flashes.clear();
		for (auto& [section, sound] : g_explode_sounds)
			xr_delete(sound);
		g_explode_sounds.clear();
		xr_delete(g_wallmarks);
		g_flying.clear();
	}
}
