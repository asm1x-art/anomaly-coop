/*
	Common functions used by lighting 
	Material table
	
	/////////////////
	Anomaly Team 2020
	/////////////////
*/
#include "common.h"

////////////////////////
//Material table
//#define MAT_FLORA 6.0
#define MAT_FLORA 0.47451
#define MAT_FLORA_ELIPSON 0.002

////////////////////////
//Simple subsurface scattering

//Author: LVutner
//Do not copy or redistribute without permission.
float SSS(float3 N, float3 V, float3 L)
{
	const float SSS_DIST = 0.125; //Scattering distortion
	const float SSS_POW = 4; //Scattering power
	const float SSS_SCALE = 0.8; //Scattering scale
	const float SSS_AMB = 0.05; //Scattering ambient
		
    float3 SSS_vector = normalize(L + N * SSS_DIST);
    float SSS_light = pow(saturate(dot(V, -SSS_vector)),SSS_POW); //DICE translucency
    SSS_light  *= (SSS_POW+2)/(2); //blinn normalize
	
    SSS_light  = SSS_light * SSS_SCALE;
    //SSS_light  += saturate(1-SSS_light) * SSS_AMB;
    SSS_light  += (1-saturate(dot(N,L))) * SSS_AMB;
    return SSS_light;
}
