#include "stdafx.h"
#include "coop_puppet.h"
#include "coop_net.h"
#include "coop_world.h"
#include "Level.h"
#include "Actor.h"
#include "Inventory.h"
#include "inventory_item.h"
#include "Weapon.h"
#include "Torch.h"
#include "HudSound.h"
#include "ParticlesObject.h"
#include "ai_sounds.h"
#include "../xrEngine/IRenderable.h"
#include "../xrEngine/bone.h"
#include "../xrcdb/ispatial.h"
#include "../Include/xrRender/Kinematics.h"
#include "../Include/xrRender/KinematicsAnimated.h"

namespace coop
{
	static const float SNAP_DISTANCE = 5.f; // farther than this from where it should be: jump there
	static const float FOLLOW_RATE = 12.f;  // states come 10 times a second; a puppet closes the gap this fast

	enum EActorAction : u8
	{
		eShot,        // u8 EShotFlags
		eWeaponState, // u8 the weapon's new state (CWeapon/CHUDState), for its sounds
	};
	enum EShotFlags : u8
	{
		eShotLauncher = 1 << 0,
		eShotSilenced = 1 << 1,
	};

	// the torch on a puppet: not the actor's own light definition, a plain spot that shows where it looks
	static const float TORCH_RANGE = 30.f;
	static const float TORCH_CONE = deg2rad(60.f);
	static const Fcolor TORCH_COLOR = {0.6f, 0.6f, 0.5f, 1.f};

	// how much of the look's turn each bone takes, as CActor's own bone callbacks (ActorAnimation.cpp)
	struct SBoneTurn
	{
		LPCSTR bone;
		float yaw, pitch, roll;
	};
	static const SBoneTurn BONE_TURNS[] = {
		{"bip01_spine", 0.0f, 0.0f, 0.3f},
		{"bip01_spine1", 0.4f, 0.2f, 0.3f},
		{"bip01_spine2", 0.4f, 0.7f, 0.2f},
		{"bip01_head", 0.2f, 0.1f, 0.2f},
	};
	static const u32 BONE_TURN_COUNT = sizeof(BONE_TURNS) / sizeof(BONE_TURNS[0]);

	// world model bones that show weapon addons (CWeapon::UpdateAddonsVisibility)
	struct SAddonBone
	{
		u8 flag;
		LPCSTR status_key;
		LPCSTR bone;
	};
	static const SAddonBone ADDON_BONES[] = {
		{CSE_ALifeItemWeapon::eWeaponAddonScope, "scope_status", "wpn_scope"},
		{CSE_ALifeItemWeapon::eWeaponAddonGrenadeLauncher, "grenade_launcher_status", "wpn_launcher"},
		{CSE_ALifeItemWeapon::eWeaponAddonSilencer, "silencer_status", "wpn_silencer"},
	};

	const xr_vector<shared_str>& puppet_motion_names()
	{
		static xr_vector<shared_str> names;
		if (!names.empty())
			return names;

		auto add = [](LPCSTR a, LPCSTR b = "", LPCSTR c = "", LPCSTR d = "")
		{
			string128 name;
			names.push_back(strconcat(sizeof(name), name, a, b, c, d));
		};
		static LPCSTR STANDS[] = {"_turn", "_idle_0", "_idle_1", "_death_0", "_torso_0_aim_0", "_jump_begin",
		                          "_jump_idle", "_jump_end", "_jump_end_1"};
		static LPCSTR MOVES[] = {"_walk", "_run"};
		static LPCSTR DIRECTIONS[] = {"_fwd_0", "_back_0", "_ls_0", "_rs_0"};
		static LPCSTR TORSO[] = {"_aim_0", "_aim_1", "_aim_2", "_aim_3", "_escape_0", "_holster_0", "_draw_0",
		                         "_reload_0", "_reload_1", "_reload_2", "_drop_0", "_attack_0", "_attack_1",
		                         "_attack_2", "_idle_1"};
		static LPCSTR WHOLE_BODY[] = {"_attack_0", "_attack_1", "_attack_2"};

		for (LPCSTR base : {"norm", "cr"})
		{
			for (LPCSTR stand : STANDS)
				add(base, stand);
			for (LPCSTR move : MOVES)
				for (LPCSTR direction : DIRECTIONS)
					add(base, move, direction);
			for (int slot = 1; slot <= 13; ++slot) // STorsoWpn per animation slot
			{
				string16 n;
				xr_sprintf(n, "_%d", slot);
				for (LPCSTR torso : TORSO)
					add(base, "_torso", n, torso);
				for (LPCSTR whole : WHOLE_BODY)
					add(base, "_all", n, whole);
			}
		}
		add("cl_idle_1");
		add("cl_torso_0_aim_0");
		for (LPCSTR direction : DIRECTIONS)
			add("cl_run", direction);
		for (LPCSTR other : {"norm_escape_00", "norm_escape_ls_00", "norm_escape_rs_00", "norm_escape_jump_00",
		                     "norm_escape_ls_jump_00", "norm_escape_rs_jump_00", "head_idle_0", "norm_dead_stop_0"})
			add(other);
		return names;
	}

	//------------------------------------------------------------------------------------------------
	// Our side: what our actor looks like and plays

	static shared_str g_indexed_visual;          // the actor model g_motion_index was made for
	static xr_map<u32, u16> g_motion_index;      // MotionID::val -> index in puppet_motion_names()

	static u16 motion_index(MotionID motion)
	{
		auto it = motion.valid() ? g_motion_index.find(motion.val) : g_motion_index.end();
		return it != g_motion_index.end() ? it->second : u16(-1);
	}

	void write_look(NET_Packet& P)
	{
		CActor* actor = g_actor;
		IKinematicsAnimated* K = smart_cast<IKinematicsAnimated*>(actor->Visual());
		if (K && actor->cNameVisual() != g_indexed_visual)
		{
			g_indexed_visual = actor->cNameVisual();
			g_motion_index.clear();
			const xr_vector<shared_str>& names = puppet_motion_names();
			for (u16 i = 0; i < names.size(); ++i)
			{
				MotionID motion = K->ID_Cycle_Safe(names[i]);
				if (motion.valid())
					g_motion_index.emplace(motion.val, i); // the first name of a motion wins
			}
		}

		P.w_float(Device.vCameraDirection.getP());
		// the model turns by rotateY(-(r_model_yaw + r_model_yaw_delta)) (CActor::g_Orientate)
		const Fmatrix& X = actor->XFORM();
		P.w_float(atan2f(X.k.x, X.k.z));
		const SRotation& torso = actor->Orientation();
		P.w_float(torso.yaw);
		P.w_float(torso.pitch);
		P.w_float(torso.roll);

		P.w_u16(motion_index(actor->m_current_legs));
		P.w_u16(motion_index(actor->m_current_torso));
		P.w_u16(motion_index(actor->m_current_head));
		static CBlend* torso_blend = nullptr;
		static u8 torso_seq = 0;
		if (actor->m_current_torso_blend != torso_blend)
		{
			torso_blend = actor->m_current_torso_blend;
			++torso_seq;
		}
		P.w_u8(torso_seq);

		P.w_stringZ(actor->cNameVisual());
		CInventoryItem* item = actor->inventory().ActiveItem();
		P.w_stringZ(item ? item->object().cNameSect() : shared_str(""));
		CWeapon* weapon = smart_cast<CWeapon*>(item);
		P.w_u8(weapon ? weapon->GetAddonsState() : 0);

		u8 flags = 0;
		if (weapon && weapon->GetState() == CWeapon::eReload)
			flags |= SLook::eReloading;
		CTorch* torch = smart_cast<CTorch*>(actor->inventory().ItemFromSlot(TORCH_SLOT));
		if (torch && torch->torch_active())
			flags |= SLook::eTorch;
		P.w_u8(flags);
	}

	void read_look(NET_Packet& P, SLook& look)
	{
		look.look_pitch = P.r_float();
		look.body_yaw = P.r_float();
		look.torso_yaw = P.r_float();
		look.torso_pitch = P.r_float();
		look.torso_roll = P.r_float();
		look.legs = P.r_u16();
		look.torso = P.r_u16();
		look.head = P.r_u16();
		look.torso_seq = P.r_u8();
		P.r_stringZ(look.visual);
		P.r_stringZ(look.item);
		look.item_addons = P.r_u8();
		look.flags = P.r_u8();
	}

	void on_actor_shot(const CWeapon& weapon, bool launcher)
	{
		if (!g_actor || weapon.H_Parent() != g_actor || !is_connected())
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eShot);
		P.w_u8(u8((launcher ? eShotLauncher : 0) | (weapon.IsSilencerAttached() ? eShotSilenced : 0)));
		send(P);
	}

	void on_actor_weapon_state(const CWeapon& weapon, u32 state)
	{
		if (!g_actor || weapon.H_Parent() != g_actor || !is_connected())
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eWeaponState);
		P.w_u8(u8(state));
		send(P);
	}

	//------------------------------------------------------------------------------------------------
	// Their side: a puppet per player on our level

	class CPuppet : public IRenderable, public ISpatial
	{
	public:
		CPuppet() : ISpatial(g_SpatialSpace)
		{
			renderable.visual = nullptr;
			renderable.xform.identity();
			spatial.type |= STYPE_RENDERABLE;
			for (u32 i = 0; i < BONE_TURN_COUNT; ++i)
				m_turns[i] = {this, &BONE_TURNS[i]};
		}

		virtual ~CPuppet()
		{
			spatial_unregister();
			set_item(nullptr, 0);
			if (renderable.visual)
				::Render->model_Delete(renderable.visual);
		}

		virtual IRenderable* dcast_Renderable() { return this; }
		virtual BOOL renderable_ShadowGenerate() { return TRUE; }
		virtual BOOL renderable_ShadowReceive() { return TRUE; }

		void update(const SPeer& peer)
		{
			const SLook& look = peer.look;
			if (look.visual != m_visual)
				set_body(look.visual);
			if (!renderable.visual)
				return;
			if (look.item != m_item_section || look.item_addons != m_item_addons)
				set_item(look.item, look.item_addons);
			m_flags = look.flags;

			// states come 10 times a second: follow them smoothly, jump when far behind
			if (!m_placed || m_position.distance_to(peer.position) > SNAP_DISTANCE)
			{
				m_position = peer.position;
				m_body_yaw = look.body_yaw;
				m_placed = true;
			}
			const float k = _min(1.f, Device.fTimeDelta * FOLLOW_RATE);
			m_position.lerp(m_position, peer.position, k);
			m_body_yaw = angle_lerp(m_body_yaw, look.body_yaw, k);
			m_turn = angle_lerp(m_turn, angle_normalize_signed(look.torso_yaw + look.body_yaw), k);
			m_pitch = angle_lerp(m_pitch, angle_normalize_signed(look.torso_pitch), k);
			m_roll = angle_lerp(m_roll, angle_normalize_signed(look.torso_roll), k);

			renderable.xform.rotateY(m_body_yaw);
			renderable.xform.c.set(m_position);
			spatial.sphere.P.set(m_position.x, m_position.y + 1.f, m_position.z);
			spatial.sphere.R = 2.f;
			if (spatial.node_ptr)
				spatial_move();
			else
				spatial_register();
			update_lights(peer);

			if (IKinematicsAnimated* K = renderable.visual->dcast_PKinematicsAnimated())
			{
				if (look.legs != m_legs)
					play(K, m_legs = look.legs);
				if (look.torso != m_torso || look.torso_seq != m_torso_seq)
				{
					m_torso_seq = look.torso_seq;
					play(K, m_torso = look.torso);
				}
				if (look.head != m_head)
					play(K, m_head = look.head);
			}
		}

		virtual void renderable_Render()
		{
			if (!renderable.visual)
				return;
			IKinematics* K = renderable.visual->dcast_PKinematics();
			if (IKinematicsAnimated* KA = renderable.visual->dcast_PKinematicsAnimated())
				KA->UpdateTracks(); // once a frame however often it is drawn (shadows)
			if (K)
			{
				K->CalculateBones_Invalidate();
				K->CalculateBones(TRUE);
			}
			::Render->set_Transform(&renderable.xform);
			::Render->add_Visual(renderable.visual);

			Fmatrix item_xform;
			if (m_item && K && hand_xform(K, item_xform))
			{
				item_xform.mulB_43(m_item_offset);
				::Render->set_Transform(&item_xform);
				::Render->add_Visual(m_item);
			}
		}

	private:
		struct STurnParam
		{
			CPuppet* puppet;
			const SBoneTurn* turn;
		};

		// spine and head turn to where the player looks, as CActor's Spin0Callback and the like
		static void _BCL turn_bone(CBoneInstance* B)
		{
			const STurnParam* p = static_cast<const STurnParam*>(B->callback_param());
			const CPuppet& puppet = *p->puppet;
			Fmatrix spin;
			spin.setXYZ(-puppet.m_pitch * p->turn->pitch, puppet.m_turn * p->turn->yaw, puppet.m_roll * p->turn->roll);
			const Fvector c = B->mTransform.c;
			B->mTransform.mulA_43(spin);
			B->mTransform.c = c;
		}

		void set_body(const shared_str& visual)
		{
			if (renderable.visual)
				::Render->model_Delete(renderable.visual);
			renderable.visual = nullptr;
			m_visual = visual;
			m_legs = m_torso = m_head = u16(-1);
			if (!visual.size())
				return;

			renderable.visual = ::Render->model_Create(*visual);
			IKinematics* K = renderable.visual ? renderable.visual->dcast_PKinematics() : nullptr;
			if (!K)
				return;
			for (u32 i = 0; i < BONE_TURN_COUNT; ++i)
			{
				const u16 bone = K->LL_BoneID(BONE_TURNS[i].bone);
				if (bone != BI_NONE)
					K->LL_GetBoneInstance(bone).set_callback(bctCustom, turn_bone, &m_turns[i]);
			}
			// the actor holds things with these (CActor::g_WeaponBones)
			m_hand_r = K->LL_BoneID(pSettings->r_string("actor", "weapon_bone0"));
			m_hand_l = K->LL_BoneID(pSettings->r_string("actor", "weapon_bone1"));
			m_hand_r2 = K->LL_BoneID(pSettings->r_string("actor", "weapon_bone2"));
		}

		void set_item(const shared_str& section, u8 addons)
		{
			if (m_item)
				::Render->model_Delete(m_item);
			m_item = nullptr;
			xr_delete(m_sounds);
			m_item_section = section;
			m_item_addons = addons;
			if (!section.size() || !pSettings->section_exist(section) || !pSettings->line_exist(section, "visual"))
				return;

			load_fx(section);
			m_item = ::Render->model_Create(pSettings->r_string(section, "visual"));
			m_item_offset.identity();
			if (pSettings->line_exist(section, "position") && pSettings->line_exist(section, "orientation"))
			{
				Fvector ypr = pSettings->r_fvector3(section, "orientation");
				ypr.mul(PI / 180.f);
				m_item_offset.setHPB(ypr.x, ypr.y, ypr.z);
				m_item_offset.translate_over(pSettings->r_fvector3(section, "position"));
			}
			m_one_handed = READ_IF_EXISTS(pSettings, r_u32, section, "hand_dependence", 2) == 1;

			IKinematics* K = m_item ? m_item->dcast_PKinematics() : nullptr;
			if (!K)
				return;
			for (const SAddonBone& addon : ADDON_BONES)
			{
				const u16 bone = K->LL_BoneID(addon.bone);
				if (bone == BI_NONE)
					continue;
				const int status = READ_IF_EXISTS(pSettings, r_s32, section, addon.status_key, 0);
				const bool shown = status == ALife::eAddonPermanent ||
					(status == ALife::eAddonAttachable && (addons & addon.flag));
				K->LL_SetBoneVisible(bone, shown, TRUE);
			}
			K->CalculateBones_Invalidate();
			K->CalculateBones(TRUE);
		}

		// what a shot of the item looks and sounds like, as CShootingObject and CWeaponMagazined load it
		void load_fx(const shared_str& section)
		{
			auto text = [&](LPCSTR key)
			{
				return pSettings->line_exist(section, key) ? shared_str(pSettings->r_string(section, key)) : shared_str();
			};
			auto point = [&](LPCSTR key)
			{
				return pSettings->line_exist(section, key) ? pSettings->r_fvector3(section, key) : Fvector().set(0, 0, 0);
			};
			auto color = [&](LPCSTR key, const Fcolor& def)
			{
				if (!pSettings->line_exist(section, key))
					return def;
				const Fvector c = pSettings->r_fvector3(section, key);
				return Fcolor().set(c.x, c.y, c.z, 1.f);
			};

			m_fx.flame = text("flame_particles");
			m_fx.smoke = text("smoke_particles");
			m_fx.silenced_flame = text("silencer_flame_particles");
			m_fx.silenced_smoke = text("silencer_smoke_particles");
			m_fx.launcher_flame = text("grenade_flame_particles");
			m_fx.shell = text("shell_particles");
			m_fx.fire_point = point("fire_point");
			m_fx.fire_point2 = point("fire_point2");
			m_fx.shell_point = point("shell_point");
			m_fx.light = pSettings->line_exist(section, "light_color") &&
				!READ_IF_EXISTS(pSettings, r_bool, section, "light_disabled", false);
			m_fx.light_color = color("light_color", Fcolor().set(0.6f, 0.5f, 0.3f, 1.f));
			m_fx.silenced_light_color = color("silencer_light_color", m_fx.light_color);
			m_fx.light_range = READ_IF_EXISTS(pSettings, r_float, section, "light_range", 5.f);
			m_fx.silenced_light_range = READ_IF_EXISTS(pSettings, r_float, section, "silencer_light_range", m_fx.light_range);
			m_fx.light_time = READ_IF_EXISTS(pSettings, r_float, section, "light_time", 0.2f);
			m_fx.knife = !xr_strcmp(READ_IF_EXISTS(pSettings, r_string, section, "class", ""), "WP_KNIFE");

			// heard as theirs, not as anything the AI should react to
			m_sounds = xr_new<HUD_SOUND_COLLECTION_LAYERED>();
			m_sounds->LoadSound(*section, "snd_shoot", "sndShot", false, SOUND_TYPE_NO_SOUND);
			m_sounds->LoadSound(*section, "snd_silncer_shot", "sndSilencerShot", false, SOUND_TYPE_NO_SOUND);
			m_sounds->LoadSound(*section, "snd_shoot_grenade", "sndShotG", false, SOUND_TYPE_NO_SOUND);
			m_sounds->LoadSound(*section, "snd_reload", "sndReload", true, SOUND_TYPE_NO_SOUND);
			m_sounds->LoadSound(*section, "snd_draw", "sndShow", true, SOUND_TYPE_NO_SOUND);
			m_sounds->LoadSound(*section, "snd_holster", "sndHide", true, SOUND_TYPE_NO_SOUND);
		}

		void play_sound(LPCSTR alias, const Fvector& position)
		{
			if (m_sounds && m_sounds->FindSoundItem(alias, false))
				m_sounds->PlaySound(alias, position, nullptr, false);
		}

		static void particles(const shared_str& name, const Fmatrix& where)
		{
			if (!name.size())
				return;
			CParticlesObject* ps = CParticlesObject::Create(*name, TRUE);
			ps->UpdateParent(where, Fvector().set(0, 0, 0));
			ps->Play(false);
		}

		// the item's world matrix right now; false when there's no item or no hands to hold it
		bool item_xform(Fmatrix& result)
		{
			IKinematics* K = renderable.visual ? renderable.visual->dcast_PKinematics() : nullptr;
			if (!m_item || !K)
				return false;
			K->CalculateBones(TRUE); // not drawn lately (behind us): the bones may be stale
			if (!hand_xform(K, result))
				return false;
			result.mulB_43(m_item_offset);
			return true;
		}

	public:
		void shot(u8 flags)
		{
			Fmatrix item;
			if (!item_xform(item))
				return;
			const bool launcher = !!(flags & eShotLauncher);
			const bool silenced = !!(flags & eShotSilenced);

			Fmatrix muzzle = item;
			item.transform_tiny(muzzle.c, launcher ? m_fx.fire_point2 : m_fx.fire_point);
			if (launcher)
				particles(m_fx.launcher_flame, muzzle);
			else
			{
				particles(silenced && m_fx.silenced_flame.size() ? m_fx.silenced_flame : m_fx.flame, muzzle);
				particles(silenced && m_fx.silenced_smoke.size() ? m_fx.silenced_smoke : m_fx.smoke, muzzle);
				Fmatrix shell = item;
				item.transform_tiny(shell.c, m_fx.shell_point);
				particles(m_fx.shell, shell);
			}
			LPCSTR sound = launcher ? "sndShotG" : "sndShot";
			if (silenced && !launcher && m_sounds && m_sounds->FindSoundItem("sndSilencerShot", false))
				sound = "sndSilencerShot";
			play_sound(sound, muzzle.c);

			if (m_fx.light && !launcher)
			{
				if (!m_shot_light)
				{
					m_shot_light = ::Render->light_create();
					m_shot_light->set_type(IRender_Light::POINT);
					m_shot_light->set_shadow(false);
				}
				m_shot_light->set_color(silenced ? m_fx.silenced_light_color : m_fx.light_color);
				m_shot_light->set_range(silenced ? m_fx.silenced_light_range : m_fx.light_range);
				m_shot_light->set_position(muzzle.c);
				m_shot_light->set_active(true);
				m_shot_light_until = Device.fTimeGlobal + m_fx.light_time;
			}
		}

		void weapon_state(u8 state)
		{
			Fmatrix item;
			const Fvector at = item_xform(item) ? item.c : m_position;
			switch (state)
			{
			case CWeapon::eReload: play_sound("sndReload", at); break;
			case CHUDState::eShowing: play_sound("sndShow", at); break;
			case CHUDState::eHiding: play_sound("sndHide", at); break;
			case CWeapon::eFire:
			case CWeapon::eFire2:
				if (m_fx.knife) // a knife's swing isn't a shot: OnShot doesn't hear it
					play_sound("sndShot", at);
				break;
			}
		}

	private:
		// the torch shines where the player looks, from the head
		void update_lights(const SPeer& peer)
		{
			if (m_shot_light && m_shot_light->get_active() && Device.fTimeGlobal >= m_shot_light_until)
				m_shot_light->set_active(false);

			const bool torch = !!(m_flags & SLook::eTorch);
			if (torch && !m_torch)
			{
				m_torch = ::Render->light_create();
				m_torch->set_type(IRender_Light::SPOT);
				m_torch->set_shadow(true);
				m_torch->set_range(TORCH_RANGE);
				m_torch->set_cone(TORCH_CONE);
				m_torch->set_color(TORCH_COLOR);
			}
			if (!m_torch)
				return;
			m_torch->set_active(torch);
			if (!torch)
				return;

			IKinematics* K = renderable.visual->dcast_PKinematics();
			const u16 head = K ? K->LL_BoneID("bip01_head") : BI_NONE;
			Fvector from = m_position;
			from.y += 1.6f;
			if (head != BI_NONE)
				renderable.xform.transform_tiny(from, K->LL_GetTransform(head).c);
			Fvector dir, right;
			dir.setHP(peer.yaw, peer.look.look_pitch);
			right.crossproduct(Fvector().set(0.f, 1.f, 0.f), dir).normalize_safe();
			m_torch->set_position(from);
			m_torch->set_rotation(dir, right);
		}

		// where the item in hands goes, as CWeapon::UpdateXForm does it for an actor
		bool hand_xform(IKinematics* K, Fmatrix& result) const
		{
			if (m_hand_r == BI_NONE || m_hand_l == BI_NONE || m_hand_r2 == BI_NONE)
				return false;
			const u16 left = (m_one_handed || (m_flags & SLook::eReloading)) ? m_hand_r2 : m_hand_l;
			const Fmatrix& mL = K->LL_GetTransform(left);
			const Fmatrix& mR = K->LL_GetTransform(m_hand_r);
			Fvector D;
			D.sub(mL.c, mR.c);
			if (fis_zero(D.magnitude()))
			{
				result.identity();
				result.c.set(mR.c);
			}
			else
			{
				Fvector R, N;
				D.normalize();
				R.crossproduct(mR.j, D);
				N.crossproduct(D, R);
				N.normalize();
				result.set(R, N, D, mR.c);
			}
			result.mulA_43(renderable.xform);
			return true;
		}

		static void play(IKinematicsAnimated* K, u16 index)
		{
			const xr_vector<shared_str>& names = puppet_motion_names();
			if (index >= names.size())
				return;
			const MotionID motion = K->ID_Cycle_Safe(names[index]);
			if (motion.valid())
				K->PlayCycle(motion);
		}

		shared_str m_visual;
		bool m_placed = false;
		Fvector m_position = {0.f, 0.f, 0.f};
		float m_body_yaw = 0.f;
		float m_turn = 0.f, m_pitch = 0.f, m_roll = 0.f; // torso relative to the body
		STurnParam m_turns[BONE_TURN_COUNT];
		u16 m_legs = u16(-1), m_torso = u16(-1), m_head = u16(-1);
		u8 m_torso_seq = 0;
		u8 m_flags = 0;

		u16 m_hand_r = BI_NONE, m_hand_l = BI_NONE, m_hand_r2 = BI_NONE;
		IRenderVisual* m_item = nullptr;
		shared_str m_item_section;
		u8 m_item_addons = 0;
		Fmatrix m_item_offset;
		bool m_one_handed = false;

		struct SItemFX
		{
			shared_str flame, smoke, silenced_flame, silenced_smoke, launcher_flame, shell;
			Fvector fire_point, fire_point2, shell_point; // in the item's model
			bool light;
			Fcolor light_color, silenced_light_color;
			float light_range, silenced_light_range, light_time;
			bool knife;
		} m_fx = {};
		HUD_SOUND_COLLECTION_LAYERED* m_sounds = nullptr;
		ref_light m_shot_light;
		float m_shot_light_until = 0.f;
		ref_light m_torch;
	};

	static xr_map<u32, CPuppet*> g_puppets; // peer id -> its puppet

	void update_puppets()
	{
		if (!world_ready())
			return;

		const peers_t& list = peers();
		const shared_str& level = Level().name();
		for (auto it = g_puppets.begin(); it != g_puppets.end();)
		{
			auto peer = list.find(it->first);
			if (peer == list.end() || peer->second.level != level || !peer->second.has_look)
			{
				xr_delete(it->second);
				it = g_puppets.erase(it);
			}
			else
				++it;
		}

		for (const auto& [id, peer] : list)
		{
			if (peer.level != level || !peer.has_look)
				continue;
			CPuppet*& puppet = g_puppets[id];
			if (!puppet)
			{
				puppet = xr_new<CPuppet>();
				Msg("[coop] '%s' is here: puppet made", peer.name.c_str());
			}
			puppet->update(peer);
		}
	}

	void on_peer_action(u32 sender, NET_Packet& P)
	{
		auto it = g_puppets.find(sender);
		if (it == g_puppets.end())
			return; // not on our level: nothing to see or hear
		switch (P.r_u8())
		{
		case eShot: it->second->shot(P.r_u8()); break;
		case eWeaponState: it->second->weapon_state(P.r_u8()); break;
		}
	}

	void clear_puppets()
	{
		for (auto& [id, puppet] : g_puppets)
			xr_delete(puppet);
		g_puppets.clear();
	}
}
