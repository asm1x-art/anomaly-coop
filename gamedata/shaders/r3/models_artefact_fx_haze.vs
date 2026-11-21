// Artefact heat haze (models_artefact_fx_haze.s l_special): the artefact's mesh blown up along its normals by
// bus_obj_artefact_fx4.x metres, drawn into the distortion buffer, so the air round it wavers.
#include "common.h"
#include "skin.h"
#include "screenspace_mvectors.h"

uniform float4 bus_obj_artefact_fx4;	// x: how far out (m), y: strength, 0 = off

struct v2p_afx
{
	float2 tc0	: TEXCOORD0;	// base
	float3 nv	: TEXCOORD1;	// normal, eye space
	float3 pv	: TEXCOORD2;	// position, eye space
	float4 hpos	: SV_Position;
};

v2p_afx _main(v_model v)
{
	v2p_afx o;
	float4 P = v.P;
	P.xyz += normalize((float3)v.N) * bus_obj_artefact_fx4.x;
	o.hpos = mul(m_WVP, P);
	o.tc0 = v.tc.xy;
	o.pv = mul(m_WV, P);
	o.nv = mul((float3x3)m_WV, (float3)v.N);
	o.hpos.xy = ssfx_taa_jitter(o.hpos);
	return o;
}

/////////////////////////////////////////////////////////////////////////
#ifdef 	SKIN_NONE
v2p_afx	main(v_model v) 			{ return _main(v); }
#endif

#ifdef 	SKIN_0
v2p_afx	main(v_model_skinned_0 v) 	{ return _main(skinning_0(v)); }
#endif

#ifdef	SKIN_1
v2p_afx	main(v_model_skinned_1 v) 	{ return _main(skinning_1(v)); }
#endif

#ifdef	SKIN_2
v2p_afx	main(v_model_skinned_2 v) 	{ return _main(skinning_2(v)); }
#endif

#ifdef	SKIN_3
v2p_afx	main(v_model_skinned_3 v) 	{ return _main(skinning_3(v)); }
#endif

#ifdef	SKIN_4
v2p_afx	main(v_model_skinned_4 v) 	{ return _main(skinning_4(v)); }
#endif

FXVS;
