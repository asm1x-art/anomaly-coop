#include "stdafx.h"
#include "coop_heli.h"
#include "coop_net.h"
#include "coop_puppet.h"
#include "coop_world.h"
#include "Level.h"
#include "helicopter.h"
#include "ParticlesObject.h"
#include "../xrphysics/PhysicsShell.h"
#include "../Include/xrRender/Kinematics.h"

namespace coop
{
	static const u32 FRESH_MS = 500;       // as an NPC's (coop_npc.cpp): older, the authority no longer has it online
	static const u32 LIST_LIVE_MS = 500;   // the authority's list came this lately: one not in it isn't online there
	// a puppet's health never goes under it: bind_heli brings a helicopter down below 0.005, and here only the death
	// the authority sends may (coop_world.cpp apply_vehicle_death), so that its game says who downed it
	static const float HEALTH_FLOOR = 0.01f;

	enum EHeliFlags : u8
	{
		fDead = 1 << 0,
		fExploded = 1 << 1,
		fFlame = 1 << 2,   // burning (bind_heli's flame_start_health)
		fLight = 1 << 3,
		fEngine = 1 << 4,  // its engine is heard (TurnEngineSound)
		fFiring = 1 << 5,  // the machine gun fires: its muzzle flame goes on between the shots
	};

	enum EShotKind : u8
	{
		eHeliBullet, // vec3 muzzle, vec3 direction, u8 shot number, s32 seed: as CHelicopter::OnShot fired it
		eHeliRocket, // vec3 where it left: its launch sound (the rocket flies as any, coop_projectiles.cpp)
	};

	struct SHeliState
	{
		Fvector position;
		Fvector velocity;  // m/s, to fly on with between the states
		Fvector hpb;       // XFORM().getHPB
		Fvector2 gun;      // m_cur_rot: how the machine gun is turned
		float health;
		u8 flags;
		u32 received;      // Device.dwTimeContinual
	};

	struct SHeliPuppet
	{
		bool placed = false;
		bool hidden = false;
		Fvector position;
		Fvector hpb;
		Fvector2 gun;
	};

	static xr_map<u16, SHeliState> g_states;   // from the authority of our level, by helicopter id
	static xr_map<u16, SHeliPuppet> g_puppets;
	static u32 g_last_list = 0;                // when the authority's list last came
	static u32 g_shots = 0, g_rockets = 0;     // shown since the last coop_debug line

	// [coop_heli] in mod_system_coop.ltx
	struct SHeliSettings
	{
		float follow_rate = 6.f;    // 1/s: how fast a puppet closes in on where the authority's is
		float snap_distance = 30.f; // m: farther off than this it is put there at once
		float fly_on_s = 0.5f;      // s: how long a puppet flies on with the last velocity heard
	};

	static const SHeliSettings& settings()
	{
		static SHeliSettings s;
		static bool loaded = false;
		if (!loaded && pSettings)
		{
			loaded = true;
			s.follow_rate = READ_IF_EXISTS(pSettings, r_float, "coop_heli", "follow_rate", s.follow_rate);
			s.snap_distance = READ_IF_EXISTS(pSettings, r_float, "coop_heli", "snap_distance", s.snap_distance);
			s.fly_on_s = READ_IF_EXISTS(pSettings, r_float, "coop_heli", "fly_on_s", s.fly_on_s);
		}
		return s;
	}

	static bool others_on_our_level()
	{
		const shared_str& level = Level().name();
		for (const auto& [id, peer] : peers())
			if (peer.level == level)
				return true;
		return false;
	}

	// another player runs our level (coop_npc.cpp puppet_level) and the others have this helicopter too
	bool is_heli_puppet(const CHelicopter* heli)
	{
		return heli && is_connected() && g_pGameLevel && !is_authority(Level().name()) && others_on_our_level() &&
			!is_local_object(heli->ID());
	}

	static bool on_level_with_others_as_authority()
	{
		return is_connected() && g_pGameLevel && world_ready() && is_authority(Level().name()) && others_on_our_level();
	}

	//------------------------------------------------------------------------------------------------
	// What of a helicopter the stream carries, and how a puppet shows it

	struct SHeliAccess
	{
		static void write(NET_Packet& P, CHelicopter& heli)
		{
			const bool dead = heli.state() == CHelicopter::eDead;
			P.w_u16(heli.ID());
			P.w_vec3(heli.XFORM().c);
			Fvector velocity;
			if (dead)
				heli.PHGetLinearVell(velocity); // falling, or lying
			else
			{
				velocity.setHP(heli.m_movement.currPathH, heli.m_movement.currPathP);
				velocity.mul(heli.m_movement.curLinearSpeed);
			}
			P.w_vec3(velocity);
			Fvector hpb;
			heli.XFORM().getHPB(hpb.x, hpb.y, hpb.z);
			P.w_vec3(hpb);
			P.w_float(heli.m_cur_rot.x);
			P.w_float(heli.m_cur_rot.y);
			P.w_float(heli.GetfHealth());
			u8 flags = 0;
			if (dead)
				flags |= fDead;
			if (heli.m_exploded)
				flags |= fExploded;
			if (heli.m_flame_started)
				flags |= fFlame;
			if (heli.m_light_started)
				flags |= fLight;
			if (heli.m_engine_on && !dead)
				flags |= fEngine;
			if (heli.IsWorking())
				flags |= fFiring;
			P.w_u8(flags);
		}

		static void set_hidden(CHelicopter& heli, SHeliPuppet& puppet, bool hidden)
		{
			if (puppet.hidden == hidden)
				return;
			puppet.hidden = hidden;
			heli.setVisible(!hidden);
			heli.setEnabled(!hidden); // bullets pass
			if (hidden)
			{
				heli.m_engineSound.set_volume(0.f);
				heli.StopFlameParticles();
			}
			else
				heli.m_engineSound.set_volume(heli.m_engine_on ? 1.f : 0.f);
		}

		// where the authority's is now: its last state, flown on for as long as it is old
		static void follow(CHelicopter& heli, SHeliPuppet& puppet, const SHeliState& state)
		{
			const SHeliSettings& cfg = settings();
			const float age = _min(float(Device.dwTimeContinual - state.received) / 1000.f, cfg.fly_on_s);
			Fvector target;
			target.mad(state.position, state.velocity, age);
			if (!puppet.placed || puppet.position.distance_to(target) > cfg.snap_distance)
			{
				puppet.position = target;
				puppet.hpb = state.hpb;
				puppet.gun = state.gun;
				puppet.placed = true;
			}
			// it flies on as the authority's does, and closes in on where that one is: no lag behind it at speed
			if (age < cfg.fly_on_s)
				puppet.position.mad(state.velocity, Device.fTimeDelta);
			const float k = _min(1.f, Device.fTimeDelta * cfg.follow_rate);
			puppet.position.lerp(puppet.position, target, k);
			puppet.hpb.x = angle_lerp(puppet.hpb.x, state.hpb.x, k);
			puppet.hpb.y = angle_lerp(puppet.hpb.y, state.hpb.y, k);
			puppet.hpb.z = angle_lerp(puppet.hpb.z, state.hpb.z, k);
			puppet.gun.x = angle_lerp(puppet.gun.x, state.gun.x, k);
			puppet.gun.y = angle_lerp(puppet.gun.y, state.gun.y, k);

			heli.XFORM().setHPB(puppet.hpb.x, puppet.hpb.y, puppet.hpb.z);
			heli.XFORM().translate_over(puppet.position);
			heli.m_cur_rot.set(puppet.gun);
			const bool dead = heli.state() == CHelicopter::eDead;
			if (CPhysicsShell* shell = heli.PPhysicsShell())
			{
				shell->SetTransform(heli.XFORM(), mh_unspecified);
				if (dead && shell->isEnabled())
					shell->Disable(); // something bumped it awake: it lies where the authority's lies, not where it rolls
			}

			// should this game run it next (the authority left), it flies on from here at this speed
			heli.m_movement.currP = puppet.position;
			heli.m_body.currBodyHPB = puppet.hpb;
			const float speed = state.velocity.magnitude();
			heli.m_movement.curLinearSpeed = dead ? 0.f : speed;
			if (speed > EPS_L)
				state.velocity.getHP(heli.m_movement.currPathH, heli.m_movement.currPathP);

			if (!dead && !is_dying_remotely(heli.ID()))
				heli.SetfHealth(_max(state.health, HEALTH_FLOOR));

			const bool engine = (state.flags & fEngine) && !dead;
			if (engine != heli.m_engine_on)
				heli.TurnEngineSound(engine);
			if (!!(state.flags & fLight) != heli.m_light_started)
				heli.TurnLighting(!!(state.flags & fLight));
			if ((state.flags & fFlame) && !heli.m_flame_started)
				heli.StartFlame();
			if (!(state.flags & fFiring))
				heli.StopFlameParticles();
			if ((state.flags & fExploded) && !heli.m_exploded)
				explode(heli); // the effects come with the explosion (eExplosion), whichever is first
		}

		// every frame, fresh state or not: the muzzle (for the shots' flame and light), smoke, sounds, bones
		static void show(CHelicopter& heli)
		{
			IKinematics* K = smart_cast<IKinematics*>(heli.Visual());
			heli.m_fire_bone_xform = K->LL_GetTransform(heli.m_fire_bone);
			heli.m_fire_bone_xform.mulA_43(heli.XFORM());
			heli.m_fire_pos.set(0.f, 0.f, 0.f);
			heli.m_fire_bone_xform.transform_tiny(heli.m_fire_pos);
			heli.UpdateFlameParticles();
			heli.UpdateLight();
			heli.UpdateHeliParticles();
			if (heli.m_engineSound._feedback())
				heli.m_engineSound.set_position(heli.XFORM().c);
			if (heli.m_brokenSound._feedback())
				heli.m_brokenSound.set_position(heli.XFORM().c);
			K->CalculateBones();
		}

		// what CHelicopter::ExplodeHelicopter does besides the explosion itself
		static void explode(CHelicopter& heli)
		{
			if (heli.m_exploded)
				return;
			heli.m_ready_explode = false;
			heli.m_exploded = true;
			if (heli.m_pParticle)
			{
				heli.m_pParticle->Stop();
				CParticlesObject::Destroy(heli.m_pParticle);
			}
			if (heli.CPHDestroyable::CanDestroy())
				heli.CPHDestroyable::Destroy(heli.ID(), "physic_destroyable_object");
			heli.m_brokenSound.stop();
			heli.m_layered_sounds.PlaySound("sndExplode", heli.Position(), &heli, false);
		}

		static void shot(CHelicopter& heli, const Fvector& position, const Fvector& direction, int shot_num, s32 seed)
		{
			heli.coop_blank_bullet(position, direction, heli.m_CurrentAmmo, heli.ID(), heli.ID(), shot_num, seed);
			// the rest of CHelicopter::OnShot
			heli.StartShotParticles();
			if (heli.m_bLightShotEnabled)
				heli.Light_Start();
			heli.StartFlameParticles();
			heli.StartSmokeParticles(position, zero_vel);
			heli.OnShellDrop(position, zero_vel);
			heli.m_layered_sounds.PlaySound("sndShoot", position, &heli, false);
		}

		static void rocket(CHelicopter& heli, const Fvector& position)
		{
			heli.m_layered_sounds.PlaySound("sndRocket", position, &heli, false);
		}
	};

	//------------------------------------------------------------------------------------------------
	// The authority's side

	u32 write_heli_states(NET_Packet& P)
	{
		xr_vector<CHelicopter*> helis;
		for (u32 i = 0, n = Level().Objects.o_count(); i < n; ++i)
		{
			CHelicopter* heli = smart_cast<CHelicopter*>(Level().Objects.o_get_by_iterator(i));
			// one broken into pieces is gone (CPHDestroyable::PhysicallyRemoveSelf): the others' goes as well
			if (heli && !heli->getDestroy() && heli->getVisible() && !is_local_object(heli->ID()))
				helis.push_back(heli);
		}
		const u8 count = u8(_min(u32(helis.size()), u32(255)));
		P.w_u8(count);
		for (u8 i = 0; i < count; ++i)
			SHeliAccess::write(P, *helis[i]);
		// coop_debug 1: once a second, where ours are as we send them
		static u32 last = 0;
		if (debug_mode && count && Device.dwTimeContinual - last >= 1000)
		{
			last = Device.dwTimeContinual;
			for (u8 i = 0; i < count; ++i)
			{
				const Fvector& p = helis[i]->Position();
				Msg("[coop heli] %s (id=%u) ours at %.1f %.1f %.1f, health %.3f, %s%s", helis[i]->cName().c_str(), helis[i]->ID(),
				    p.x, p.y, p.z, helis[i]->GetfHealth(), helis[i]->state() == CHelicopter::eDead ? "dead" : "alive",
				    helis[i]->IsWorking() ? ", firing" : "");
			}
		}
		return count;
	}

	void on_heli_shot(CHelicopter& heli, const Fvector& position, const Fvector& direction, int shot_num, s32 seed)
	{
		if (!on_level_with_others_as_authority() || is_local_object(heli.ID()))
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eHeliShot);
		P.w_u16(heli.ID());
		P.w_u8(eHeliBullet);
		P.w_vec3(position);
		P.w_vec3(direction);
		P.w_u8(u8(shot_num));
		P.w_s32(seed);
		send(P);
	}

	void on_heli_rocket(CHelicopter& heli, const Fvector& position)
	{
		if (!on_level_with_others_as_authority() || is_local_object(heli.ID()))
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eHeliShot);
		P.w_u16(heli.ID());
		P.w_u8(eHeliRocket);
		P.w_vec3(position);
		send(P);
	}

	//------------------------------------------------------------------------------------------------
	// Everybody else's side

	void read_heli_states(NET_Packet& P)
	{
		g_last_list = Device.dwTimeContinual;
		for (u8 count = P.r_u8(); count; --count)
		{
			SHeliState& state = g_states[P.r_u16()];
			P.r_vec3(state.position);
			P.r_vec3(state.velocity);
			P.r_vec3(state.hpb);
			state.gun.x = P.r_float();
			state.gun.y = P.r_float();
			state.health = P.r_float();
			state.flags = P.r_u8();
			state.received = Device.dwTimeContinual;
		}
	}

	// coop_debug 1: once a second, how a puppet helicopter follows
	static void debug_heli(CHelicopter& heli, const SHeliState* state, const SHeliPuppet& puppet)
	{
		static u32 last = 0;
		if (!debug_mode || Device.dwTimeContinual - last < 1000)
			return;
		last = Device.dwTimeContinual;
		const Fvector& p = heli.Position();
		Msg("[coop heli] %s (id=%u) puppet%s at %.1f %.1f %.1f: state %d ms old, %.1f m off it, health %.3f, flags %x, "
		    "%s, %u shots %u rockets shown",
		    heli.cName().c_str(), heli.ID(), puppet.hidden ? " (hidden)" : "", p.x, p.y, p.z,
		    state ? int(Device.dwTimeContinual - state->received) : -1,
		    state ? p.distance_to(state->position) : -1.f, heli.GetfHealth(), state ? state->flags : 0,
		    heli.state() == CHelicopter::eDead ? "dead" : "alive", g_shots, g_rockets);
		g_shots = g_rockets = 0;
	}

	bool drive_heli_puppet(CHelicopter& heli)
	{
		if (!is_heli_puppet(&heli))
		{
			auto it = g_puppets.find(heli.ID());
			if (it != g_puppets.end())
			{
				// our game runs it from now on, from where it was shown
				SHeliAccess::set_hidden(heli, it->second, false);
				g_puppets.erase(it);
			}
			return false;
		}
		SHeliPuppet& puppet = g_puppets[heli.ID()];
		auto it = g_states.find(heli.ID());
		const bool fresh = it != g_states.end() && Device.dwTimeContinual - it->second.received < FRESH_MS;
		// the authority sends helicopters and not this one: not online in its game
		SHeliAccess::set_hidden(heli, puppet, !fresh && Device.dwTimeContinual - g_last_list < LIST_LIVE_MS);
		if (fresh)
			SHeliAccess::follow(heli, puppet, it->second);
		SHeliAccess::show(heli);
		debug_heli(heli, fresh ? &it->second : nullptr, puppet);
		return true;
	}

	void play_heli_shot(u32 sender, NET_Packet& P)
	{
		const u16 id = P.r_u16();
		const u8 kind = P.r_u8();
		Fvector position, direction;
		P.r_vec3(position);
		int shot_num = 0;
		s32 seed = 0;
		if (kind == eHeliBullet)
		{
			P.r_vec3(direction);
			shot_num = P.r_u8();
			seed = P.r_s32();
		}
		if (!world_ready())
			return;
		auto peer = peers().find(sender);
		if (peer == peers().end() || peer->second.level != Level().name())
			return;
		CHelicopter* heli = smart_cast<CHelicopter*>(Level().Objects.net_Find(id));
		auto puppet = g_puppets.find(id);
		if (!heli || !is_heli_puppet(heli) || (puppet != g_puppets.end() && puppet->second.hidden))
			return;
		if (kind == eHeliBullet)
		{
			SHeliAccess::shot(*heli, position, direction, shot_num, seed);
			++g_shots;
		}
		else if (kind == eHeliRocket)
		{
			SHeliAccess::rocket(*heli, position);
			++g_rockets;
		}
	}

	void on_heli_exploded(CHelicopter& heli)
	{
		if (is_heli_puppet(&heli))
			SHeliAccess::explode(heli);
	}

	void clear_heli_sync()
	{
		g_states.clear();
		g_puppets.clear();
		g_last_list = 0;
	}
}
