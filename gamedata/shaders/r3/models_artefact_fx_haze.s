-- Artefact glow overlay with a heat haze (rare ones, artefact_fx.script): the glow as models_artefact_fx.s, the haze
-- its l_special, which the engine draws in the distortion pass (r__dsgraph_build.cpp, r_dsgraph_insert_dynamic).
function normal		(shader, t_base, t_second, t_detail)
	shader	: begin		("models_artefact_fx", "models_artefact_fx")
			: blend		(true, blend.one, blend.one)
			: zb		(true, false)
			: fog		(false)
	shader:dx10texture	("s_base", t_base)
	shader:dx10sampler	("smp_base")
end

function l_special	(shader, t_base, t_second, t_detail)
	shader	: begin		("models_artefact_fx_haze", "models_artefact_fx_haze")
			: sorting	(3, false)
			: blend		(true, blend.srcalpha, blend.invsrcalpha)
			: zb		(true, false)
			: fog		(false)
			: distort	(true)
	shader:dx10texture	("s_distort", "pfx\\pfx_dist2")
	shader:dx10sampler	("smp_linear")
end
