#ifndef ASH_GROUND_H
#define ASH_GROUND_H

// Co-op: ash settling on the ground during the Ash front (coop_zone_ash.script, [zone_event_ash] ground_* in
// mod_system_zone_events.ltx). Full screen passes over the G-buffer after the rain's (CRenderTarget::draw_ash):
// surfaces that face up, are open to the sky and are not living things go grey, matte and smooth as the cover grows.
//   ash_amount        rt_Accumulator = the new view space normal (xyz) and how much ash (w); the costly one
//   ash_apply_albedo  rt_Color rgb toward the ash's albedo (blend src alpha)
//   ash_apply_gloss   rt_Color alpha (gloss) down (blend zero, src alpha)
//   ash_apply_normal  rt_Position xy = the new normal where there is ash
// The lanes (docs/shader_bus.md), all 0 = the default:
//   bus_ash_cover  x cover 0..1 (the script ramps it), y the most the ash hides (opacity), z gloss kept under full ash,
//                  w patchiness (0: even; 1: patches first, the rest later)
//   bus_ash_look   xyz the ash's albedo, w the size of its patches in metres
//   bus_ash_mask   x..y world normal.y from no ash to full, z..w hemi (open sky) from no ash to full
//   bus_ash_shape  x how far full ash turns the normal up (smooths the surface's bumps), y grain (albedo variation),
//                  w debug views: 1 yellow leaves, orange bark, red flora material, blue tree LODs, green the rest;
//                  2 the hemi; 3 how much ash (white); 4 red facing, green open sky, blue alive
//   bus_ash_flora  foliage (leaves, bushes, grass: Anomaly's flora material 6) and far tree LODs (material 0): their
//                  normals point every way and a crown hides itself from above, so x..y world normal.y from no ash to
//                  full, z the most of it (x opacity), w how much the view from above and the hemi are ignored
//   bus_ash_bark   tree trunks and branches (ASH_BARK): x..y world normal.y from no ash to full, z the most of it;
//                  the view from above and the hemi ignored as for foliage
// ash_smap (engine): x 1 while the rain's shadow map (the view from above) is valid, y..z view distance where it fades
// out (beyond it only the hemi tells a roof). m_shadow (the map's xform) comes from shadow.h.

#include "common.h"
#include "shadow.h"

uniform float4 bus_ash_cover;
uniform float4 bus_ash_look;
uniform float4 bus_ash_mask;
uniform float4 bus_ash_shape;
uniform float4 bus_ash_flora;
uniform float4 bus_ash_bark;
uniform float4 ash_smap;

Texture2D s_heat;         // HeatVision's target: x > 0 on living things
Texture2D s_ash;          // ash_amount's result (rt_Accumulator): xyz normal, w amount
static float3 ash_dbg;    // debug view 4: ash_amount's facing, open sky and alive

float ash_hash(float2 p)
{
	float3 p3 = frac(float3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return frac((p3.x + p3.y) * p3.z);
}

float ash_vnoise(float2 p)
{
	float2 i = floor(p);
	float2 f = frac(p);
	float2 u = f * f * (3.0 - 2.0 * f);
	float a = ash_hash(i);
	float b = ash_hash(i + float2(1, 0));
	float c = ash_hash(i + float2(0, 1));
	float d = ash_hash(i + float2(1, 1));
	return lerp(lerp(a, b, u.x), lerp(c, d, u.x), u.y);
}

// the G-buffer keeps a material in 5 bits (gbuf_pack_hemi_mtl): Anomaly's flora (material 6) comes out as 11, the
// tree LODs (lod.ps writes 0) as 0; a material 1..4 lands on 2, 8, 14, 20, 26 (a weight moves it a little up)
#define ASH_MTL_FLORA 11
#define ASH_MTL_LOD 0

// view space position and normal of the pixel, hemi, the material's 5 bit id
void ash_gbuffer(float2 tc, float4 pos2d, out float3 P, out float3 N, out float hemi, out uint mtl)
{
	float4 G = s_position.Sample(smp_nofilter, tc);
	P = float3(G.z * (pos2d.xy * pos_decompression_params.zw - pos_decompression_params.xy), G.z);
	N = gbuf_unpack_normal(G.xy);
	hemi = gbuf_unpack_hemi(G.w);
	mtl = uint(round(gbuf_unpack_mtl(G.w) * 31.0 / 1.333333333));
}

// trees and bushes: their pixel shaders are compiled with ASH_FOLIAGE (leaves) or ASH_BARK (trunks), which put 0.5 or
// 0.75 into the heat target's alpha (gbuffer_stage.h); foliage textures with Anomaly's flora material and the far tree
// LODs by the material
#define ASH_KIND_GROUND 0
#define ASH_KIND_FLORA 1
#define ASH_KIND_BARK 2

uint ash_kind(float heat_w, uint mtl)
{
	if (abs(heat_w - 0.75) < 0.1)
		return ASH_KIND_BARK;
	if (abs(heat_w - 0.5) < 0.1 || mtl == ASH_MTL_FLORA || mtl == ASH_MTL_LOD)
		return ASH_KIND_FLORA;
	return ASH_KIND_GROUND;
}

uint ash_kind_at(float2 tc, uint mtl)
{
	return ash_kind(s_heat.Sample(smp_nofilter, tc).w, mtl);
}

float ash_patch_noise(float3 Pw)
{
	float2 wp = Pw.xz / (bus_ash_look.w > 0 ? bus_ash_look.w : 6.0);
	return 0.55 * ash_vnoise(wp) + 0.3 * ash_vnoise(wp * 2.7 + 5.1) + 0.15 * ash_vnoise(wp * 7.3 + 1.7);
}

// 0..1, how much ash a pixel has (opacity included)
float ash_amount(float2 tc, float4 pos2d, float3 P, float3 N, float hemi, uint mtl)
{
	float cover = bus_ash_cover.x;
	float opacity = bus_ash_cover.y > 0 ? bus_ash_cover.y : 0.85;
	float spread = bus_ash_cover.w;
	float4 mask = any(bus_ash_mask) ? bus_ash_mask : float4(0.35, 0.8, 0.03, 0.2);

	float3 Pw = mul(m_inv_V, float4(P, 1.0));
	float3 Nw = normalize(mul(m_inv_V, float4(N, 0.0)));

	// the face normal from the neighbouring pixels' positions (derivatives: before any branch). Some models (crates,
	// tyres, props) and the trees keep a shading normal in the G-buffer that does not face as the surface does; where
	// the depth jumps (an object's outline) the face normal is not one, the G-buffer's stands
	float3 Ng = normalize(cross(ddy(Pw), ddx(Pw)));
	if (dot(Ng, eye_position - Pw) < 0)
		Ng = -Ng;
	bool outline = (abs(ddx(P.z)) + abs(ddy(P.z))) > 0.05 * P.z;
	float face_y = outline ? Nw.y : max(Nw.y, Ng.y);

	// faces up (the G-buffer's normal or the face's, whichever is more up: grass cards keep theirs), open sky
	float up = smoothstep(mask.x, mask.y, face_y);
	float sky = smoothstep(mask.z, mask.w, hemi);

	// the view from above (the rain's shadow map): roofs, cars, trees over it keep it clean
	float above = 1.0;
	if (ash_smap.x > 0)
	{
		float4 PS = mul(m_shadow, float4(P, 1.0));
		float s = shadow_rain(PS, Pw.xz + Nw.xz * 0.02);
		above = lerp(s, 1.0, smoothstep(ash_smap.y, ash_smap.z, length(P)));
	}

	// not the HUD, not living things
	float4 H = s_heat.Sample(smp_nofilter, tc);
	float hud = smoothstep(1.0, 1.3, length(P));
	float alive = saturate(H.x * 4.0);

	// foliage and tree LODs: a softer facing, the crown's own shade from above and its hemi mostly ignored;
	// trunks: their upper sides
	float open = sky * above;
	uint kind = ash_kind(H.w, mtl);
	float4 flora = any(bus_ash_flora) ? bus_ash_flora : float4(-0.6, 0.5, 0.9, 0.8);
	if (kind == ASH_KIND_FLORA)
	{
		up = smoothstep(flora.x, flora.y, Nw.y) * flora.z;
		open = lerp(open, 1.0, flora.w);
	}
	else if (kind == ASH_KIND_BARK)
	{
		// the trees' normals are bent for their lighting (a trunk's point up): the bark faces as its geometry does
		float4 bark = any(bus_ash_bark) ? bus_ash_bark : float4(0.0, 0.7, 0.8, 0);
		up = smoothstep(bark.x, bark.y, outline ? 0 : Ng.y) * bark.z;
		open = lerp(open, 1.0, flora.w);
	}

	// patches first: the noise decides where a cover below 1 has settled
	float grow = saturate(cover * (1.0 + spread) - ash_patch_noise(Pw) * spread);

	ash_dbg = float3(saturate(up), saturate(open), alive);
	return saturate(grow * up * open * hud * (1.0 - alive)) * opacity;
}

// the ash's albedo at a pixel: a fine grain (gone with distance) and the patches so it is not flat
float3 ash_color(float3 P)
{
	float3 look = any(bus_ash_look.xyz) ? bus_ash_look.xyz : float3(0.42, 0.41, 0.40);
	float amp = bus_ash_shape.y > 0 ? bus_ash_shape.y : 0.36;
	float3 Pw = mul(m_inv_V, float4(P, 1.0));
	float grain = ash_vnoise(Pw.xz * 3.1) * 0.6 + ash_vnoise(Pw.xz * 11.0) * 0.4;
	grain = lerp(grain, 0.5, smoothstep(15.0, 60.0, P.z));
	return look * (1.0 + amp * (grain - 0.5)) * (0.9 + 0.2 * ash_patch_noise(Pw));
}

float4 ash_load(float2 tc)
{
	return s_ash.Sample(smp_nofilter, tc);
}

#endif
