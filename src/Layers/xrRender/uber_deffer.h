#pragma once

// _ps_define (DX11 only): a define the pixel shader is compiled with, as its own shader "<ps>(<define>)" (the trees'
// ASH_FOLIAGE, ash_ground.h)
void uber_deffer(CBlender_Compile& C, bool hq, LPCSTR _vspec, LPCSTR _pspec, BOOL _aref, LPCSTR _detail_replace = 0,
                 bool DO_NOT_FINISH = false, bool DO_NOT_WRITE = false, LPCSTR _ps_define = 0);
void uber_shadow(CBlender_Compile& C, LPCSTR _vspec);
