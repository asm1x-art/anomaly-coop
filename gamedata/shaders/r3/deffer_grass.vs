#include "common.h"

float4 consts; // {1/quant,1/quant,diffusescale,ambient}
float4 wave; // cx,cy,cz,tm
float4 dir2D; 
float4 array[61*4];
/*
	Updated grass shader
	
	-Supports normal mapping
	-Simple SSS approx. (Spherical normals)
	
	Credits: 
	-Zagolski - Faster normal mapping code

	Keep this header in, and put credits onto your mod page. 
	Thanks.
*/

v2p_bumped 	main (v_detail v)
{
	v2p_bumped 		O;
	// index
	int 	i 	= v.misc.w;
	float4  m0 	= array[i+0];
	float4  m1 	= array[i+1];
	float4  m2 	= array[i+2];
	float4  c0 	= array[i+3];

	// Transform pos to world coords
	float4 pos;
 	pos.x = dot(m0, v.pos);
 	pos.y = dot(m1, v.pos);
 	pos.z = dot(m2, v.pos);
	pos.w = 1;
	
	//Wave effect
	float base = m1.w;
	float dp = calc_cyclic   (dot(pos,wave));
	float H = pos.y - base;			// height of vertex (scaled)
	float frac = v.misc.z*consts.x;		// fractional
	float inten = H * dp;
	float2 result = calc_xz_wave(dir2D.xz*inten,frac);
	pos = float4(pos.x+result.x, pos.y, pos.z+result.y, 1);
	
	
	// Calculate the 3x3 transform from tangent space to eye-space
	// TangentToEyeSpace = object2eye * tangent2object
	//		    = object2eye * transpose(object2tangent) (since the inverse of a rotation is its transpose)	
	
	float3 flatN = float3(0,1,0); //vertical normal
	
	//
	float3 VertPosN1 = float3(0,H,0); //vertical pos
	float3 VertPosN2 = float3(result.x,0,result.y); //offset pos
	float3 VertPosN3 = normalize(VertPosN1 + VertPosN2); //normal from offset from base
	float3 baseP = float3(m0.w,m1.w,m2.w); //base world space position
	float3 VertPosN4 = normalize(pos - baseP); //normal from offset from base
	//
	
	float3 sphereOffset = float3(0.00, 1.00, 0.00);
	sphereOffset += 10 * float3(-result.x, 0.0, -result.y);
	float3 sphereScale = float3(1.0, 2.0, 1.0);
	float3 sphereN = normalize(sphereScale * v.pos.xyz + sphereOffset); //Spherical normals trick
	
	float3 camFacingN = normalize((mul(m_W,  pos) - eye_position.xyz) * float3(-1,0,-1));
	
	float3 folaigeN = lerp(camFacingN, VertPosN4, saturate(H)); //roots face the camera, the tips face the sky
	//float3 folaigeN = lerp(camFacingN, sphereN, saturate(H)); //roots face the camera, the tips face the sky
	
	folaigeN.xz *= 0.5;;
	folaigeN.y = sqrt(1 - saturate(dot(folaigeN.xz, folaigeN.xz)));
	folaigeN = normalize(folaigeN);
	
	//tangent basis
	float3 N = folaigeN;
	
	float3 B = float3(0,0,1);
	if (abs(dot(N, B)) > 0.99f) B = float3(0,1,0);
	
	float3 T = normalize(cross(N, B));
	
	
	//TBN matrix
	float3x3 xform	= mul((float3x3)m_WV, float3x3(
						T.x,B.x,N.x,
						T.y,B.y,N.y,
						T.z,B.z,N.z
				));

	O.M1 = xform[0]; 
	O.M2 = xform[1]; 
	O.M3 = xform[2]; 

	// Final out
	float4 Pp = mul(m_WVP,	pos);
	O.hpos = Pp;
	float3 Pe = mul(m_WV,  pos);
	O.tcdh = float4((v.misc * consts).xyyy);

#if defined(USE_R2_STATIC_SUN)
	O.tcdh.w = c0.x; // (,,,dir-occlusion)
#endif
	O.position = float4(Pe, c0.w);

	return O;
}
FXVS;
