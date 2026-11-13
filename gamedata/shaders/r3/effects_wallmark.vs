#include "common.h"

#include "screenspace_mvectors.h"

//////////////////////////////////////////////////////////////////////////////////////////
// Vertex
v2p_TL main ( v_TL I )
{
	v2p_TL O;

	O.HPos = mul( m_VP, I.P );
	O.Tex0 = I.Tex0;
	O.Color = I.Color.bgra;	//	swizzle vertex colour

	// Test TAA
	O.HPos.xy = ssfx_taa_jitter(O.HPos);

 	return O;
}