// Artefact glow overlay (models_artefact_fx.s, artefact_fx.script): the artefact's own mesh once more, in the emissive
// pass over its own G-buffer drawing. The position is worked out as the G-buffer's (deffer_model_*: m_WVP + the TAA
// jitter), so the depth test (less-equal, no write) lets it lie exactly on the surface.
#include "common.h"
#include "skin.h"
#include "screenspace_mvectors.h"

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
	o.hpos = mul(m_WVP, v.P);
	o.tc0 = v.tc.xy;
	o.pv = mul(m_WV, v.P);
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
