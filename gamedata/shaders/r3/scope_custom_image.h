/*
	=====================================================================
	Addon      : Shader 3D Scopes
	Link       : https://www.moddb.com/mods/stalker-anomaly/addons/shader-3d-scopes
	Authors    : LVutner, party_50

	All credit to original authors.
	=====================================================================
*/

#include "scope_3dss_common.h"

#define LCD_RES float2(640,640)

float2 SCOPECOORD_TO_TEXCOORD_SCREEN(float2 sc) {
	if (!isSVPActive() && scope_phase & SCOPE_PHASE_IMAGE) {
		// This is fake pip mode, so we have to correct the coordinates
		// FIXME: These coordinates need to be rotated to align with eye up
		float screen_delta  = length(ddy(scope.hpos.xy * output_res.zw));
		float texture_delta = length(ddy(scope.tc0.xy));
		float tc_multiplier = texture_delta / screen_delta;

		sc -= 0.5;

		float angle = hack_tex_angle;

		sc = float2( sc.x * cos(angle) - sc.y * sin(angle)
		           , sc.x * sin(angle) + sc.y * cos(angle));

		float f = (digitalZoom() * tc_multiplier);
		return ASPECT_UNCORRECT_TC(sc / f + 0.5);

	} else {
		return sc;
	}
}

float3 scope_custom_image(Scope s) {
	
	int FFP = s3ds_param_1.w;
	float CHROMA_POWER = s3ds_param_3.w;
	float2 reticle_tc = FFP ? s.ffp : s.sfp;
	
	float current_zoom = (curMag()-minMag()) * 0.4 + 1.0;
	
	float3x3 TBN = cotangent_frame(s.v_N + 0.0039, s.v_P + 0.0039, s.tc0.xy);
	float3 V_tangent = normalize(float3(dot(-s.v_P, TBN[0]), dot(-s.v_P, TBN[1]), dot(-s.v_P, TBN[2])));
	
	float2 coord = s.sfp;
	if (RETICLE_TYPE == RT_SCREEN || RETICLE_TYPE == RT_FLAT_SCREEN) {
		coord = s.tc0;
	}

	float2 scope_tc = SCOPECOORD_TO_TEXCOORD(coord);
	
	if (RETICLE_TYPE != RT_FLAT_SCREEN)
	{
		float2 fish = fisheye(s.tc0, (V_tangent.xy * mas_scale())) / current_zoom;
		scope_tc += fish;
		reticle_tc += fish;
	}
	
	bool blur = SETTING(SETTINGS, ST_NVG_BLUR) && floor(shader_param_8.x) != 0 || zoomRotateFactor() == 0;
	
	float3 back = back_image_sample(s.tc0, scope_tc, CHROMA_POWER, blur, SETTING(SETTINGS, ST_CHROMATISM));
	if ((IMAGE_TYPE == IT_THERMAL || IMAGE_TYPE == IT_THERMAL_COLOR) && markswitch_current.x < 2) {
		if (SETTING(SETTINGS, ST_THERMAL_PIXELATION)) {
			float pixelate = curMag();

			float2 sfp = (floor(coord * LCD_RES / pixelate) * pixelate + 0.5) / LCD_RES;
			scope_tc = SCOPECOORD_TO_TEXCOORD_SCREEN(sfp);
		}

		float2 rez = screen_res.xy;

		gbuffer_data gbd = gbuffer_load_data(scope_tc, scope_tc * rez.xy, 0);
		back = infrared(gbd, scope_tc * rez.xy, scope_tc);
		if (markswitch_current.x == 1) {
			back = 1 - back;
		}
		if (IMAGE_TYPE == IT_THERMAL_COLOR) {
		    back = s_heat_map.Sample(smp_base, float2(back.x, 0.5));
		}
	} else {
		// FIXME: Incorrect colorspace
		back *= LENS_COLOR;
	}

	if (false) {
		if (IMAGE_TYPE == IT_THERMAL || IMAGE_TYPE == IT_THERMAL_COLOR) {
			float SUBPIXELS = (LCD_RES * 4.0);
			float digitalZoom = SETTING(SETTINGS, ST_THERMAL_PIXELATION)
				? curMag()
				: 1.0;

			float multiplier = (SUBPIXELS / digitalZoom);

			float2 c = (coord - s.center) * multiplier + SUBPIXELS*10;

			// The LCD effect is designed for 1:1 pixel ratio, and LCD effect in general requires high output resolution to look correct.
			// It is absolutely necessary to multisample to get even a barely passable output.
			float2 o = float2(0.25,-0.25);
			float3 s = lcd_effect(c)
					+ lcd_effect(c + o.xx)
					+ lcd_effect(c + o.yy)
					+ lcd_effect(c + o.xy)
					+ lcd_effect(c + o.yx);

			back *= s / 5.0;
		}
	}

	if (IMAGE_TYPE == IT_NV && markswitch_current.x == 0) {
		// FIXME: Incorrect colorspace
		back = apply_nvg(scope_tc, back);
	}

	return back;
}