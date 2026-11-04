#pragma once

// Grass hides from AI sight (docs/coop/ai.md). The level's grass (level.details: 2x2 m slots, up to four detail models
// each with a density per quarter) has no collision, so a sight ray never meets it. This walks the last metres of an
// NPC's sight ray before the point it looks at and, wherever the ray runs inside a slot's grass layer (from the slot's
// ground up to its grass height), takes away sight in proportion to the grass density and the length run through it.
// Someone standing in grass shows above it; lying or crouching in thick grass is hidden.
// Settings: [ai_grass] in system.ltx (mod_system_ai_tuning.ltx).
namespace grass_occlusion
{
	// the share of sight left between from and to (1 = not hidden at all); also level.grass_transparency(from, to)
	float transparency(const Fvector& from, const Fvector& to);
}

// console ai_grass 0/1: switch the grass's hiding off and on in a running game (for comparing in one place)
extern int g_ai_grass;
