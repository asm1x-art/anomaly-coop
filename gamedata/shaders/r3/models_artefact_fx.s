-- Artefact glow overlay: never an object's own shader, put over an artefact's surfaces by artefact_fx.script
-- (game_object:set_overlay_shader); the engine draws its first element in the emissive pass, adding light
-- (r__dsgraph_build.cpp, r_dsgraph_insert_dynamic). Colours and strengths: mod_system_artefact_fx.ltx.
function normal		(shader, t_base, t_second, t_detail)
	shader	: begin		("models_artefact_fx", "models_artefact_fx")
			: blend		(true, blend.one, blend.one)
			: zb		(true, false)
			: fog		(false)
	shader:dx10texture	("s_base", t_base)
	shader:dx10sampler	("smp_base")
end
