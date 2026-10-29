/*
	=====================================================================
	Addon      : Shader 3D Scopes
	Link       : https://www.moddb.com/mods/stalker-anomaly/addons/shader-3d-scopes
	Authors    : LVutner, party_50
	PiP Author : m22

	God-Queen who fixed everything: MsPizza727

	All credit to original authors.
	=====================================================================
*/

#include "scope_3dss_common.h"

float4 scope_custom_reticle(Scope S) {
	float RETICLE_SIZE = s3ds_param_1.x;
	float EYE_RELIEF = s3ds_param_1.y;
	float EXIT_PUPIL = s3ds_param_1.z;
	int FFP = s3ds_param_1.w;
	
	float REFLECTION_HUE = s3ds_param_2.x;
	int MIN_ZOOM_1X = s3ds_param_2.z;
	
	float DIRT_INTENSITY = s3ds_param_3.z;
	float CHROMA_POWER = s3ds_param_3.w;
		
	float RETICLE_PROJECT = 10;
	float SHADOW_WIDTH = 0.15;
	
	if (RETICLE_TYPE == RT_FLAT_SCREEN)
		RETICLE_PROJECT = 0;

	float current_zoom = (curMag()-minMag()) * 0.4 + 1.0;
	float zoom_part = zoomPercent();

	float3x3 TBN = cotangent_frame(S.v_N + 0.0039, S.v_P + 0.0039, S.tc0.xy);
	float3 V_tangent = normalize(float3(dot(-S.v_P, TBN[0]), dot(-S.v_P, TBN[1]), dot(-S.v_P, TBN[2])));
	
	if (!SETTING(SETTINGS, ST_CHROMATISM)) {
		CHROMA_POWER = 0;
	}
	
	float lum = current_lum();

	// Sight reticle
	float2 reticle_lens_tc = project(S.tc0, (V_tangent.xy * mas_scale()), RETICLE_PROJECT, RETICLE_SIZE);
	float2 reticle_tc = project(S.tc0, (V_tangent.xy * mas_scale()), RETICLE_PROJECT, RETICLE_SIZE * (FFP || RETICLE_TYPE == RT_GIPERON || RETICLE_TYPE == RT_DFP ? current_zoom : 1));

	if (RETICLE_TYPE == RT_SCREEN || RETICLE_TYPE == RT_FLAT_SCREEN) {
		reticle_lens_tc = S.tc0;
		reticle_tc = S.tc0;
	}
	
	if (RETICLE_TYPE != RT_FLAT_SCREEN)
	{
		float2 fish = fisheye(S.tc0, (V_tangent.xy * mas_scale())) / current_zoom;
		reticle_lens_tc += fish;
		reticle_tc += fish;
	}

    float4 mark_texture = float4(0, 0, 0, 0);
	if (reticle_tc.x >= 0 && reticle_tc.x <= 1 && reticle_tc.y >= 0 && reticle_tc.y <= 1)
	{
		if (RETICLE_TYPE == RT_MARK_MAGNIFIER)
		{
			reticle_tc = mark_adjust(reticle_tc);
		}
		float2 tc = SCOPECOORD_TO_TEXCOORD(clamp(reticle_tc, 0, 1));
		mark_texture = s_reticle.Sample(smp_base, tc);

		// Try and determine whether the texture is transparent or not.
		//    Sample from two coordinates that are likely to be "transparent" in case mipmaps are missing
		bool opaque1 = s_reticle.SampleLevel(smp_base, float2(0.233, 0.1), 24).a > .99;
		bool opaque2 = s_reticle.SampleLevel(smp_base, float2(0.1, 0.233), 24).a > .99;
		if (opaque1 && opaque2)
			mark_texture.a = length(mark_texture.xyz);
	}
	
	if (RETICLE_TYPE == RT_DFP)
	{
		float4 tex_ffp = float4(0,0,0,0);
		float4 tex_sfp = float4(0,0,0,0);

		if (reticle_tc.x >= 0 && reticle_tc.x <= 1 && reticle_tc.y >= 0 && reticle_tc.y <= 1)
			tex_ffp = s_reticle.Sample(smp_base, SCOPECOORD_TO_TEXCOORD(clamp(reticle_tc, 0, 1)));;

		if (reticle_lens_tc.x >= 0 && reticle_lens_tc.x <= 1 && reticle_lens_tc.y >= 0 && reticle_lens_tc.y <= 1)
			tex_sfp = s_reticle.Sample(smp_base, SCOPECOORD_TO_TEXCOORD(clamp(reticle_lens_tc, 0, 1)));

		float vis = max(tex_ffp.r, tex_sfp.g);
		float led = tex_sfp.b;

		float4 base_lines = float4(0.0, 0.0, 0.0, vis);
		float4 led_layer  = float4(markswitch_color.rgb, led);

		mark_texture = rgba_blend(base_lines, led_layer);
	}
	
	float4 giperon_sfp;
	if (RETICLE_TYPE == RT_GIPERON)
	{
		mark_texture = mark_texture.r;
		float finder = s_reticle.Sample(smp_base, SCOPECOORD_TO_TEXCOORD(clamp(reticle_lens_tc, 0, 1))).g;
		float shift_3x = 0.053;
		float angle = -PI * (zoom_part + shift_3x) / (1 + shift_3x);
		float2 tc = reticle_lens_tc - 0.5;
		tc = float2(tc.x * cos(angle) - tc.y * sin(angle), tc.x * sin(angle) + tc.y * cos(angle));
		tc += 0.5;
		float numbers = s_reticle.Sample(smp_base, SCOPECOORD_TO_TEXCOORD(clamp(tc, 0, 1))).b;
		giperon_sfp = float4(0, 0, 0, max(finder, numbers));
	}

	if (RETICLE_TYPE == RT_ACOG)
	{
		float3 black = float3(0, 0, 0);
		float3 text = float3(0.3, 0.3, 0.3);
		float tritium_lum = 0.15;
		mark_texture = rgba_blend(rgba_blend(float4(black, mark_texture.r), float4(markswitch_color.rgb * max(tritium_lum, lum * 2), mark_texture.g)), float4(text, mark_texture.b * lum));
	}
	
	if (RETICLE_TYPE == RT_LED || RETICLE_TYPE == RT_GIPERON)
	{
		mark_texture = float4(markswitch_color.rgb, mark_texture.a);
		giperon_sfp = float4(markswitch_color.rgb, giperon_sfp.a);
	}
	
	if (RETICLE_TYPE == RT_SPECTER)
	{
		float3 black = float3(0, 0, 0);
		float4 light = float4(0, 0, 0, 0);
		if (markswitch_current.x == 1)
			light = float4(markswitch_color.rgb, mark_texture.g);
		if (markswitch_current.x == 2)
			light = float4(markswitch_color.rgb, mark_texture.b);
		
		mark_texture = rgba_blend(float4(black, mark_texture.r), light);
	}
	
	// Sight bound
    float4 mark_shadow = sample_shadow(reticle_lens_tc, 0.05);
	if (RETICLE_TYPE == RT_SCREEN || RETICLE_TYPE == RT_FLAT_SCREEN){
		mark_shadow *= 0.0;
	} else {
		if ((distance(S.sfp,S.center) > S.radius) && (RETICLE_TYPE != RT_MARK_MAGNIFIER))
			mark_shadow = float4(0,0,0,1);
	}
	
	// LED-illuminated inside walls
	float4 inside = s_inside.Sample(smp_base, SCOPECOORD_TO_TEXCOORD(clamp((reticle_tc - 0.5) * 0.62 + 0.5, 0, 1)));
	inside = float4(markswitch_color.rgb * inside.r, inside.a);
	if (RETICLE_TYPE == RT_SCREEN || RETICLE_TYPE == RT_FLAT_SCREEN || RETICLE_TYPE == RT_SPECTER || RETICLE_TYPE == RT_ACOG || RETICLE_TYPE == RT_MARK_MAGNIFIER || FFP) {
		inside = float4(0, 0, 0, 0);
	}
	
	if (RETICLE_TYPE == RT_LED_MASKED)
	{
		float3 black = float3(0, 0, 0);
		mark_texture = rgba_blend(float4(black, mark_texture.r), float4(markswitch_color.rgb, mark_texture.g));
	}
	
	if (!SETTING(SETTINGS, ST_SEE_THROUGH))
	{
		mark_texture.rgb *= zoomRotateFactor();
		giperon_sfp.rgb *= zoomRotateFactor();
	}
	
	float4 final_scope = float4(0, 0, 0, 0);	
	final_scope = rgba_blend(final_scope, mark_shadow);
	final_scope = rgba_blend(final_scope, inside*1.5);	
	mark_texture = rgba_blend(mark_texture, final_scope);

	return RETICLE_TYPE == RT_GIPERON 
		? rgba_blend(mark_texture, giperon_sfp)
		: mark_texture;
}