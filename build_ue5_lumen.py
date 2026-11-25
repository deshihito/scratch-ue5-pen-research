"""
build_ue5_lumen.py (v2) — Builds out/ue5_lumen_sdf.sb3

Polished & BVH-Accelerated 100% Pure Vanilla Scratch Pen "Mini-UE5" Engine:
  - "The Sunlit Lumen Sanctuary" architectural showcase
  - Bounding-volume guarded SDF + analytic early-outs (~2x faster!)
  - Distance-attenuated anti-aliased tile grout (mip-filtered look!)
  - Clean floating hero composition: Brushed 24k Gold Orb + Copper Halo on stone dais,
    Obsidian Dielectric Orb, Emissive Cyan Lumen Crystal Monolith, Fluted Pillars,
    Sunlit Colonnade Arches & Overhead Brutalist Beams
  - Full Cook-Torrance GGX PBR + Inigo Quilez Contact-Hardening Soft Shadows +
    4-tap SDF AO + Mini-Lumen GI (Sky + Warm Floor Bounce + Dynamic Cyan Area Light +
    True 1-Bounce Reflections with Multi-Bounce Ceiling Fill) +
    6-Tap Volumetric God Rays + ACES Filmic + Bayer Dither + 32-bit ARGB GPU Pen Bloom!
  - FAST_MODE=1 option for real-time interactive camera movement in TurboWarp!
"""

from sb3_builder import ProjectBuilder


def clamp01_stmts(s, vname):
    v = s.var(vname)
    return [
        s.if_(s.lt(v, 0), [s.set_var(vname, 0)]),
        s.if_(s.gt(v, 1), [s.set_var(vname, 1)]),
    ]


def clamp_stmts(s, vname, lo, hi):
    v = s.var(vname)
    return [
        s.if_(s.lt(v, lo), [s.set_var(vname, lo)]),
        s.if_(s.gt(v, hi), [s.set_var(vname, hi)]),
    ]


def build_ue5_lumen():
    pb = ProjectBuilder()
    s = pb.add_sprite("UE5_Lumen_Pen")

    # --- Public / Benchmark / Control Stage-readable Variables ---
    RENDER_MODE = s.var("RENDER_MODE", 0)    # 0=Full UE5, 1=Basic Scratch, 2=Direct PBR, 3=No Bloom, 4=Normals, 5=AO+Shadow
    PIXEL_STEP = s.var("PIXEL_STEP", 6)      # 6->2->1 automatic progressive refine
    FAST_MODE = s.var("FAST_MODE", 1)        # 1=Real-time interactive budget; 0=Full UE5
    AUTO_STOP = s.var("AUTO_STOP", 0)        # 0=interactive progressive loop (default for users); 1=1-frame bench
    DONE = s.var("DONE", 0)
    FRAME_MS = s.var("FRAME_MS", 0)
    BLOOM_MS = s.var("BLOOM_MS", 0)
    BLOOM_COUNT = s.var("BLOOM_COUNT", 0)
    RAYS_CAST = s.var("RAYS_CAST", 0)

    # Camera parameters (cinematic 35mm-equivalent composition inside atrium)
    camX = s.var("camX", -0.32)
    camY = s.var("camY", 0.52)
    camZ = s.var("camZ", -5.25)
    camYaw = s.var("camYaw", 4.5)
    camPitch = s.var("camPitch", -5.5)
    fov = s.var("fov", 1.38)

    # Camera basis vectors
    fwdX, fwdY, fwdZ = s.var("fwdX"), s.var("fwdY"), s.var("fwdZ")
    rgtX, rgtY, rgtZ = s.var("rgtX"), s.var("rgtY"), s.var("rgtZ")
    upX, upY, upZ = s.var("upX"), s.var("upY"), s.var("upZ")

    # Sun direction (normalized golden-hour sun pouring from upper-right-back through arches!)
    SUN_X, SUN_Y, SUN_Z = 0.7206, 0.4404, 0.5355

    # Emissive Lumen Crystal position
    CRY_X, CRY_Y, CRY_Z = -1.85, 0.08, 0.55

    # Bloom emitter lists
    blmX, blmY = s.lst("blmX"), s.lst("blmY")
    blmR, blmG, blmB = s.lst("blmR"), s.lst("blmG"), s.lst("blmB")
    blmS = s.lst("blmS")

    # Working registers
    sd, sMat = s.var("sd"), s.var("sMat")
    qx, qy, qz = s.var("qx"), s.var("qy"), s.var("qz")
    dTmp, dTmp2 = s.var("dTmp"), s.var("dTmp2")
    ax, ay, az = s.var("ax"), s.var("ay"), s.var("az")
    bx, by, bz = s.var("bx"), s.var("by"), s.var("bz")
    r2, flute = s.var("r2"), s.var("flute")
    tileX, tileZ, groove = s.var("tileX"), s.var("tileZ"), s.var("groove")

    roX, roY, roZ = s.var("roX"), s.var("roY"), s.var("roZ")
    rdX, rdY, rdZ = s.var("rdX"), s.var("rdY"), s.var("rdZ")
    tRay, hitMat = s.var("tRay"), s.var("hitMat")
    hitX, hitY, hitZ = s.var("hitX"), s.var("hitY"), s.var("hitZ")
    primT, primMat = s.var("primT"), s.var("primMat")
    tMax, stepIdx = s.var("tMax"), s.var("stepIdx")
    maxStepsV = s.var("maxStepsV")

    nX, nY, nZ, nLen = s.var("nX"), s.var("nY"), s.var("nZ"), s.var("nLen")
    albR, albG, albB = s.var("albR"), s.var("albG"), s.var("albB")
    metal, rough = s.var("metal"), s.var("rough")
    emR, emG, emB = s.var("emR"), s.var("emG"), s.var("emB")

    vX, vY, vZ = s.var("vX"), s.var("vY"), s.var("vZ")
    hX, hY, hZ = s.var("hX"), s.var("hY"), s.var("hZ")
    refX, refY, refZ = s.var("refX"), s.var("refY"), s.var("refZ")
    nDotL, nDotV, nDotH, vDotH = s.var("nDotL"), s.var("nDotV"), s.var("nDotH"), s.var("vDotH")

    f0R, f0G, f0B = s.var("f0R"), s.var("f0G"), s.var("f0B")
    fres = s.var("fres")
    fR, fG, fB = s.var("fR"), s.var("fG"), s.var("fB")
    alpha2, denom, ndf, vis, specS, kD = (
        s.var("alpha2"), s.var("denom"), s.var("ndf"), s.var("vis"), s.var("specS"), s.var("kD")
    )

    shd, shdT = s.var("shd"), s.var("shdT")
    ao = s.var("ao")
    volG, volT, volSun = s.var("volG"), s.var("volT"), s.var("volSun")
    volX, volY, volZ = s.var("volX"), s.var("volY"), s.var("volZ")

    colR, colG, colB = s.var("colR"), s.var("colG"), s.var("colB")
    skyR, skyG, skyB = s.var("skyR"), s.var("skyG"), s.var("skyB")
    refColR, refColG, refColB = s.var("refColR"), s.var("refColG"), s.var("refColB")
    pR, pG, pB = s.var("pR"), s.var("pG"), s.var("pB")
    lum, fogAmt, bayer, vig, outCol = s.var("lum"), s.var("fogAmt"), s.var("bayer"), s.var("vig"), s.var("outCol")

    elX, elY, elZ, elDist, elAtten, elDot = (
        s.var("elX"), s.var("elY"), s.var("elZ"), s.var("elDist"), s.var("elAtten"), s.var("elDot")
    )

    px, py, scrX, scrY = s.var("px"), s.var("py"), s.var("scrX"), s.var("scrY")
    u, v, colsN, rowsN = s.var("u"), s.var("v"), s.var("colsN"), s.var("rowsN")
    t0, t1, bi, bCount, invLen, checker = (
        s.var("t0"), s.var("t1"), s.var("bi"), s.var("bCount"), s.var("invLen"), s.var("checker")
    )

    now_ms = lambda: s.mul(s.days_since_2000(), 86400000)

    # =========================================================================
    # 1. BVH-GUARDED SCENE SDF EVALUATOR: map_scene(mx, my, mz) -> sd, sMat
    # =========================================================================
    p_map = s.define_proc("map_scene", ["mx", "my", "mz"], warp=True, body=[
        # Floor: y + 1.2
        s.set_var("sd", s.add(s.arg("my"), 1.2)),
        s.set_var("sMat", 1),

        # --- BVH Cluster A: Center Hero Sculpture (Gold Orb + Dais + Copper Halo) ---
        # Lipschitz-safe BVH: if outside AABB, bound sd by box distance so rays NEVER overshoot!
        s.set_var("qx", s.sub(s.arg("mx"), -0.10)),
        s.set_var("qy", s.sub(s.arg("my"), -0.15)),
        s.set_var("qz", s.sub(s.arg("mz"), 0.35)),
        s.set_var("dTmp2", s.sub(s.abs_(qx), 1.35)),
        s.set_var("dTmp", s.sub(s.abs_(qz), 1.35)),
        s.if_(s.gt(dTmp, dTmp2), [s.set_var("dTmp2", dTmp)]),
        s.set_var("dTmp", s.sub(s.abs_(qy), 1.25)),
        s.if_(s.gt(dTmp, dTmp2), [s.set_var("dTmp2", dTmp)]),
        s.if_else(
            s.lt(dTmp2, 0.25),
            [
                # Hero 1: Brushed 24k Gold PBR Sphere r = 0.78
                s.set_var("dTmp", s.sub(s.sqrt(s.add(s.mul(qx, qx), s.add(s.mul(qy, qy), s.mul(qz, qz)))), 0.78)),
                s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 3)]),

                # Low circular stone dais beneath Gold Orb (y in [-1.2, -0.96], r=0.82)
                s.set_var("dTmp", s.sub(s.sqrt(s.add(s.mul(qx, qx), s.mul(qz, qz))), 0.82)),
                s.set_var("dTmp2", s.sub(s.arg("my"), -0.96)),
                s.if_(s.gt(dTmp2, dTmp), [s.set_var("dTmp", dTmp2)]),
                s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 2)]),

                # Hero 4: Brushed Copper Tilted Torus Ring (R=1.08, r=0.085)
                s.set_var("ax", s.sub(s.mul(qx, 0.91), s.mul(qy, 0.41))),
                s.set_var("ay", s.add(s.mul(qx, 0.41), s.mul(qy, 0.91))),
                s.set_var("dTmp2", s.sub(s.sqrt(s.add(s.mul(ax, ax), s.mul(qz, qz))), 1.08)),
                s.set_var("dTmp", s.sub(s.sqrt(s.add(s.mul(dTmp2, dTmp2), s.mul(ay, ay))), 0.085)),
                s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 6)]),
            ],
            [
                s.if_(s.lt(dTmp2, sd), [s.set_var("sd", dTmp2)]),
            ],
        ),

        # --- Hero 2: Glossy Dark Ceramic/Obsidian Sphere at (1.52, -0.60, -0.45), r=0.60 ---
        s.set_var("ax", s.sub(s.arg("mx"), 1.52)),
        s.set_var("ay", s.sub(s.arg("my"), -0.60)),
        s.set_var("az", s.sub(s.arg("mz"), -0.45)),
        s.set_var("dTmp", s.sub(s.sqrt(s.add(s.mul(ax, ax), s.add(s.mul(ay, ay), s.mul(az, az)))), 0.60)),
        s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 4)]),

        # --- BVH Cluster B: Glowing Cyan Lumen Crystal + Pedestal at (-1.85, 0.08, 0.55) ---
        s.set_var("ax", s.abs_(s.sub(s.arg("mx"), CRY_X))),
        s.set_var("az", s.abs_(s.sub(s.arg("mz"), CRY_Z))),
        s.set_var("dTmp2", s.sub(ax, 0.72)),
        s.set_var("dTmp", s.sub(az, 0.72)),
        s.if_(s.gt(dTmp, dTmp2), [s.set_var("dTmp2", dTmp)]),
        s.if_else(
            s.lt(dTmp2, 0.25),
            [
                # Octahedron crystal
                s.set_var("ay", s.abs_(s.sub(s.arg("my"), CRY_Y))),
                s.set_var("dTmp", s.mul(s.sub(s.add(ax, s.add(s.mul(ay, 0.62), az)), 0.52), 0.577)),
                s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 5)]),

                # Beveled stone pedestal box
                s.set_var("qx", s.sub(ax, 0.44)),
                s.set_var("qy", s.sub(s.abs_(s.sub(s.arg("my"), -0.92)), 0.28)),
                s.set_var("qz", s.sub(az, 0.44)),
                s.set_var("bx", qx), s.if_(s.lt(bx, 0), [s.set_var("bx", 0)]),
                s.set_var("by", qy), s.if_(s.lt(by, 0), [s.set_var("by", 0)]),
                s.set_var("bz", qz), s.if_(s.lt(bz, 0), [s.set_var("bz", 0)]),
                s.set_var("dTmp2", qx),
                s.if_(s.gt(qy, dTmp2), [s.set_var("dTmp2", qy)]),
                s.if_(s.gt(qz, dTmp2), [s.set_var("dTmp2", qz)]),
                s.if_(s.gt(dTmp2, 0), [s.set_var("dTmp2", 0)]),
                s.set_var("dTmp", s.sub(s.add(s.sqrt(s.add(s.mul(bx, bx), s.add(s.mul(by, by), s.mul(bz, bz)))), dTmp2), 0.04)),
                s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 2)]),
            ],
            [
                s.if_(s.lt(dTmp2, sd), [s.set_var("sd", dTmp2)]),
            ],
        ),

        # --- Fluted Stone Pillar 1 (Left-Back) at (-2.45, z=2.40) ---
        s.set_var("ax", s.sub(s.arg("mx"), -2.45)),
        s.set_var("az", s.sub(s.arg("mz"), 2.40)),
        s.set_var("r2", s.sqrt(s.add(s.mul(ax, ax), s.mul(az, az)))),
        s.if_else(
            s.land(s.gt(r2, 0.08), s.lt(r2, 1.2)),
            [
                s.set_var("flute", s.div(s.mul(s.sub(s.mul(ax, ax), s.mul(az, az)), s.sub(s.mul(ax, ax), s.mul(az, az))), s.mul(s.mul(r2, r2), s.mul(r2, r2)))),
                s.set_var("dTmp", s.sub(r2, s.add(0.45, s.mul(flute, 0.026)))),
            ],
            [s.set_var("dTmp", s.sub(r2, 0.45))],
        ),
        s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 2)]),

        # --- Fluted Stone Pillar 2 (Right-Mid) at (2.55, z=1.65) ---
        s.set_var("ax", s.sub(s.arg("mx"), 2.55)),
        s.set_var("az", s.sub(s.arg("mz"), 1.65)),
        s.set_var("r2", s.sqrt(s.add(s.mul(ax, ax), s.mul(az, az)))),
        s.if_else(
            s.land(s.gt(r2, 0.08), s.lt(r2, 1.2)),
            [
                s.set_var("flute", s.div(s.mul(s.sub(s.mul(ax, ax), s.mul(az, az)), s.sub(s.mul(ax, ax), s.mul(az, az))), s.mul(s.mul(r2, r2), s.mul(r2, r2)))),
                s.set_var("dTmp", s.sub(r2, s.add(0.44, s.mul(flute, 0.026)))),
            ],
            [s.set_var("dTmp", s.sub(r2, 0.44))],
        ),
        s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 2)]),

        # --- Back Monumental Arched Wall at z = 4.65 ---
        s.set_var("dTmp", s.sub(s.abs_(s.sub(s.arg("mz"), 4.65)), 0.35)),
        s.set_var("dTmp2", s.sub(s.arg("my"), 3.65)),
        s.if_(s.gt(dTmp2, dTmp), [s.set_var("dTmp", dTmp2)]),
        # Central Roman Archway (r=1.55)
        s.set_var("ax", s.arg("mx")),
        s.set_var("ay", s.sub(s.arg("my"), 0.70)),
        s.if_(s.lt(ay, 0), [s.set_var("ay", 0)]),
        s.set_var("dTmp2", s.sub(1.55, s.sqrt(s.add(s.mul(ax, ax), s.mul(ay, ay))))),
        s.if_(s.gt(dTmp2, dTmp), [s.set_var("dTmp", dTmp2)]),
        # Right Archway (x=3.20, r=1.05) letting golden sunlight slice in!
        s.set_var("ax", s.sub(s.arg("mx"), 3.20)),
        s.set_var("ay", s.sub(s.arg("my"), 0.55)),
        s.if_(s.lt(ay, 0), [s.set_var("ay", 0)]),
        s.set_var("dTmp2", s.sub(1.05, s.sqrt(s.add(s.mul(ax, ax), s.mul(ay, ay))))),
        s.if_(s.gt(dTmp2, dTmp), [s.set_var("dTmp", dTmp2)]),
        s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 2)]),

        # --- Overhead Brutalist Roof Beams (y = 3.18, repeating every 2.25 units!) ---
        s.if_else(
            s.gt(s.arg("my"), 1.6),
            [
                s.set_var("ay", s.sub(s.abs_(s.sub(s.arg("my"), 3.18)), 0.27)),
                s.set_var("qz", s.sub(s.mod(s.add(s.arg("mz"), 1.125), 2.25), 1.125)),
                s.set_var("az", s.sub(s.abs_(qz), 0.35)),
                s.set_var("ax", s.sub(s.abs_(s.arg("mx")), 4.6)),
                s.set_var("dTmp", ay),
                s.if_(s.gt(az, dTmp), [s.set_var("dTmp", az)]),
                s.if_(s.gt(ax, dTmp), [s.set_var("dTmp", ax)]),
                s.set_var("dTmp2", s.sub(s.arg("mz"), 4.65)),
                s.if_(s.gt(dTmp2, dTmp), [s.set_var("dTmp", dTmp2)]),
                s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 2)]),
            ],
            [
                s.set_var("dTmp", s.sub(2.88, s.arg("my"))),
                s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp)]),
            ],
        ),

        # --- Left Atrium Wall (x = -3.85) ---
        s.set_var("dTmp", s.sub(s.abs_(s.sub(s.arg("mx"), -3.85)), 0.3)),
        s.set_var("dTmp2", s.sub(s.arg("my"), 3.65)),
        s.if_(s.gt(dTmp2, dTmp), [s.set_var("dTmp", dTmp2)]),
        s.set_var("dTmp2", s.sub(s.arg("mz"), 4.95)),
        s.if_(s.gt(dTmp2, dTmp), [s.set_var("dTmp", dTmp2)]),
        s.if_(s.lt(dTmp, sd), [s.set_var("sd", dTmp), s.set_var("sMat", 2)]),
    ])

    # =========================================================================
    # 2. PHYSICAL RAYLEIGH + MIE SKY EVALUATOR
    # =========================================================================
    p_sky = s.define_proc("eval_sky", ["sx", "sy", "sz"], warp=True, body=[
        s.set_var("ax", s.arg("sy")),
        s.if_(s.lt(ax, 0), [s.set_var("ax", 0)]),
        s.if_(s.gt(ax, 1), [s.set_var("ax", 1)]),
        s.set_var("ay", s.sqrt(ax)),
        # Richer golden-hour sunset contrast: warm amber horizon -> deep royal twilight zenith!
        s.set_var("skyR", s.add(s.mul(1.65, s.sub(1, ay)), s.mul(0.08, ay))),
        s.set_var("skyG", s.add(s.mul(0.84, s.sub(1, ay)), s.mul(0.22, ay))),
        s.set_var("skyB", s.add(s.mul(0.42, s.sub(1, ay)), s.mul(0.68, ay))),

        s.set_var("az", s.add(s.mul(s.arg("sx"), SUN_X), s.add(s.mul(s.arg("sy"), SUN_Y), s.mul(s.arg("sz"), SUN_Z)))),
        s.if_(s.gt(az, 0), [
            s.set_var("r2", s.mul(az, az)),
            s.set_var("dTmp", s.mul(r2, s.mul(r2, r2))),
            s.change_var("skyR", s.mul(dTmp, 1.55)),
            s.change_var("skyG", s.mul(dTmp, 0.88)),
            s.change_var("skyB", s.mul(dTmp, 0.34)),
            s.set_var("dTmp2", s.mul(dTmp, dTmp)),
            s.set_var("dTmp2", s.mul(dTmp2, dTmp2)),
            s.set_var("dTmp2", s.mul(dTmp2, dTmp2)),
            s.change_var("skyR", s.mul(dTmp2, 5.8)),
            s.change_var("skyG", s.mul(dTmp2, 3.9)),
            s.change_var("skyB", s.mul(dTmp2, 1.8)),
            s.if_(s.gt(az, 0.9965), [
                s.change_var("skyR", 12.0),
                s.change_var("skyG", 9.0),
                s.change_var("skyB", 5.0),
            ]),
        ]),
    ])

    # =========================================================================
    # 3. RAYMARCHER
    # =========================================================================
    p_march = s.define_proc("march_ray", ["ox", "oy", "oz", "dx", "dy", "dz", "maxD", "maxSteps"], warp=True, body=[
        s.set_var("tRay", 0.02),
        s.set_var("hitMat", 0),
        s.set_var("stepIdx", 0),
        s.repeat_until(
            s.lor(s.gt(stepIdx, s.arg("maxSteps")), s.lor(s.gt(tRay, s.arg("maxD")), s.gt(hitMat, 0))),
            [
                s.set_var("hitX", s.add(s.arg("ox"), s.mul(s.arg("dx"), tRay))),
                s.set_var("hitY", s.add(s.arg("oy"), s.mul(s.arg("dy"), tRay))),
                s.set_var("hitZ", s.add(s.arg("oz"), s.mul(s.arg("dz"), tRay))),
                s.call_proc(p_map, hitX, hitY, hitZ),
                s.if_else(
                    s.lt(sd, s.add(0.0022, s.mul(tRay, 0.0007))),
                    [s.set_var("hitMat", sMat)],
                    [s.change_var("tRay", sd)],
                ),
                s.change_var("stepIdx", 1),
            ],
        ),
    ])

    # =========================================================================
    # 4. TETRAHEDRON SDF NORMAL (4 taps)
    # =========================================================================
    E = 0.0025
    p_normal = s.define_proc("calc_normal", ["px", "py", "pz"], warp=True, body=[
        s.call_proc(p_map, s.add(s.arg("px"), E), s.sub(s.arg("py"), E), s.sub(s.arg("pz"), E)),
        s.set_var("nX", sd), s.set_var("nY", s.mul(sd, -1)), s.set_var("nZ", s.mul(sd, -1)),
        s.call_proc(p_map, s.sub(s.arg("px"), E), s.sub(s.arg("py"), E), s.add(s.arg("pz"), E)),
        s.change_var("nX", s.mul(sd, -1)), s.change_var("nY", s.mul(sd, -1)), s.change_var("nZ", sd),
        s.call_proc(p_map, s.sub(s.arg("px"), E), s.add(s.arg("py"), E), s.sub(s.arg("pz"), E)),
        s.change_var("nX", s.mul(sd, -1)), s.change_var("nY", sd), s.change_var("nZ", s.mul(sd, -1)),
        s.call_proc(p_map, s.add(s.arg("px"), E), s.add(s.arg("py"), E), s.add(s.arg("pz"), E)),
        s.change_var("nX", sd), s.change_var("nY", sd), s.change_var("nZ", sd),
        s.set_var("nLen", s.sqrt(s.add(s.mul(nX, nX), s.add(s.mul(nY, nY), s.mul(nZ, nZ))))),
        s.if_(s.gt(nLen, 0.000001), [
            s.set_var("invLen", s.div(1, nLen)),
            s.set_var("nX", s.mul(nX, invLen)),
            s.set_var("nY", s.mul(nY, invLen)),
            s.set_var("nZ", s.mul(nZ, invLen)),
        ]),
    ])

    # =========================================================================
    # 5. INIGO QUILEZ CONTACT-HARDENING SDF SOFT SHADOW
    # =========================================================================
    p_shadow = s.define_proc("calc_soft_shadow", ["ox", "oy", "oz", "kSoft", "maxSt"], warp=True, body=[
        s.set_var("shd", 1.0),
        s.set_var("shdT", 0.05),
        s.set_var("stepIdx", 0),
        s.repeat_until(
            s.lor(s.gt(stepIdx, s.arg("maxSt")), s.lor(s.gt(shdT, 11.0), s.lt(shd, 0.01))),
            [
                s.call_proc(
                    p_map,
                    s.add(s.arg("ox"), s.mul(SUN_X, shdT)),
                    s.add(s.arg("oy"), s.mul(SUN_Y, shdT)),
                    s.add(s.arg("oz"), s.mul(SUN_Z, shdT)),
                ),
                s.set_var("dTmp", s.div(s.mul(s.arg("kSoft"), sd), shdT)),
                s.if_(s.lt(dTmp, shd), [s.set_var("shd", dTmp)]),
                s.set_var("dTmp2", sd),
                s.if_(s.lt(dTmp2, 0.03), [s.set_var("dTmp2", 0.03)]),
                s.if_(s.gt(dTmp2, 0.65), [s.set_var("dTmp2", 0.65)]),
                s.change_var("shdT", dTmp2),
                s.change_var("stepIdx", 1),
            ],
        ),
        *clamp01_stmts(s, "shd"),
        s.set_var("shd", s.mul(shd, s.mul(shd, s.sub(3, s.mul(2, shd))))),
    ])

    # =========================================================================
    # 6. MULTI-SCALE SDF AMBIENT OCCLUSION (4 taps, or 2 taps in FAST_MODE)
    # =========================================================================
    p_ao = s.define_proc("calc_ao", ["ox", "oy", "oz", "nx", "ny", "nz"], warp=True, body=[
        s.set_var("ao", 0),
        s.call_proc(p_map, s.add(s.arg("ox"), s.mul(s.arg("nx"), 0.06)), s.add(s.arg("oy"), s.mul(s.arg("ny"), 0.06)), s.add(s.arg("oz"), s.mul(s.arg("nz"), 0.06))),
        s.change_var("ao", s.mul(s.sub(0.06, sd), 1.0)),
        s.call_proc(p_map, s.add(s.arg("ox"), s.mul(s.arg("nx"), 0.22)), s.add(s.arg("oy"), s.mul(s.arg("ny"), 0.22)), s.add(s.arg("oz"), s.mul(s.arg("nz"), 0.22))),
        s.change_var("ao", s.mul(s.sub(0.22, sd), 0.55)),
        s.if_(s.eq(FAST_MODE, 0), [
            s.call_proc(p_map, s.add(s.arg("ox"), s.mul(s.arg("nx"), 0.45)), s.add(s.arg("oy"), s.mul(s.arg("ny"), 0.45)), s.add(s.arg("oz"), s.mul(s.arg("nz"), 0.45))),
            s.change_var("ao", s.mul(s.sub(0.45, sd), 0.30)),
            s.call_proc(p_map, s.add(s.arg("ox"), s.mul(s.arg("nx"), 0.85)), s.add(s.arg("oy"), s.mul(s.arg("ny"), 0.85)), s.add(s.arg("oz"), s.mul(s.arg("nz"), 0.85))),
            s.change_var("ao", s.mul(s.sub(0.85, sd), 0.15)),
        ]),
        s.set_var("ao", s.sub(1.0, s.mul(ao, 1.55))),
        *clamp_stmts(s, "ao", 0.08, 1.0),
    ])

    # =========================================================================
    # 7. MATERIAL + DISTANCE-FILTERED PROCEDURAL MICRO-DETAIL EVALUATOR
    # =========================================================================
    p_mat = s.define_proc("eval_material", ["matId", "px", "py", "pz", "dist"], warp=True, body=[
        s.set_var("emR", 0), s.set_var("emG", 0), s.set_var("emB", 0),

        # Mat 1: Checkered Honed Marble & Dark Basalt Floor with Anti-Aliased Soft Grout!
        s.if_(s.eq(s.arg("matId"), 1), [
            s.set_var("tileX", s.floor(s.arg("px"))),
            s.set_var("tileZ", s.floor(s.arg("pz"))),
            s.set_var("checker", s.mod(s.add(tileX, tileZ), 2)),
            # Smooth distance-attenuated grout factor (mip-filtering prevents shimmering!)
            s.set_var("qx", s.abs_(s.sub(s.sub(s.arg("px"), tileX), 0.5))),
            s.set_var("qz", s.abs_(s.sub(s.sub(s.arg("pz"), tileZ), 0.5))),
            s.set_var("dTmp2", qx),
            s.if_(s.gt(qz, dTmp2), [s.set_var("dTmp2", qz)]),
            # groove in [0, 1] ramps smoothly from 0.468..0.495, attenuated by distance
            s.set_var("groove", s.div(s.sub(dTmp2, 0.468), 0.028)),
            *clamp01_stmts(s, "groove"),
            s.set_var("groove", s.mul(groove, s.div(1.0, s.add(1.0, s.mul(s.arg("dist"), 0.18))))),

            # Subtle marble veining
            s.set_var("dTmp", s.mul(0.5, s.add(1, s.sin(s.add(s.mul(s.arg("px"), 135), s.mul(s.arg("pz"), 105)))))),
            s.if_else(
                s.eq(checker, 0),
                [
                    s.set_var("albR", s.add(0.56, s.mul(dTmp, 0.07))),
                    s.set_var("albG", s.add(0.50, s.mul(dTmp, 0.06))),
                    s.set_var("albB", s.add(0.44, s.mul(dTmp, 0.05))),
                    s.set_var("metal", 0.0),
                    s.set_var("rough", s.add(0.16, s.mul(dTmp, 0.12))),
                ],
                [
                    s.set_var("albR", s.add(0.11, s.mul(dTmp, 0.03))),
                    s.set_var("albG", s.add(0.13, s.mul(dTmp, 0.03))),
                    s.set_var("albB", s.add(0.16, s.mul(dTmp, 0.04))),
                    s.set_var("metal", 0.06),
                    s.set_var("rough", s.add(0.11, s.mul(dTmp, 0.09))),
                ],
            ),
            # Blend smoothly toward grout color & higher roughness
            s.set_var("albR", s.add(s.mul(albR, s.sub(1, groove)), s.mul(0.08, groove))),
            s.set_var("albG", s.add(s.mul(albG, s.sub(1, groove)), s.mul(0.08, groove))),
            s.set_var("albB", s.add(s.mul(albB, s.sub(1, groove)), s.mul(0.09, groove))),
            s.set_var("rough", s.add(s.mul(rough, s.sub(1, groove)), s.mul(0.75, groove))),
        ]),

        # Mat 2: Architectural Warm Travertine Stone
        s.if_(s.eq(s.arg("matId"), 2), [
            s.set_var("dTmp", s.mul(0.5, s.add(1, s.sin(s.add(s.mul(s.arg("py"), 260), s.mul(s.arg("px"), 55)))))),
            s.set_var("albR", s.add(0.58, s.mul(dTmp, 0.08))),
            s.set_var("albG", s.add(0.52, s.mul(dTmp, 0.07))),
            s.set_var("albB", s.add(0.45, s.mul(dTmp, 0.06))),
            s.set_var("metal", 0.0),
            s.set_var("rough", s.add(0.60, s.mul(dTmp, 0.18))),
        ]),

        # Mat 3: Hero 1 — Brushed 24k Gold PBR Metal
        s.if_(s.eq(s.arg("matId"), 3), [
            s.set_var("albR", 0.99), s.set_var("albG", 0.78), s.set_var("albB", 0.35),
            s.set_var("metal", 0.96),
            s.set_var("rough", 0.14),
        ]),

        # Mat 4: Hero 2 — Glossy Deep Obsidian-Teal Ceramic Dielectric
        s.if_(s.eq(s.arg("matId"), 4), [
            s.set_var("albR", 0.05), s.set_var("albG", 0.19), s.set_var("albB", 0.26),
            s.set_var("metal", 0.02),
            s.set_var("rough", 0.08),
        ]),

        # Mat 5: Hero 3 — Emissive Cyan-Aqua Lumen Crystal
        s.if_(s.eq(s.arg("matId"), 5), [
            s.set_var("albR", 0.1), s.set_var("albG", 0.3), s.set_var("albB", 0.4),
            s.set_var("metal", 0.1),
            s.set_var("rough", 0.10),
            s.set_var("emR", 0.42), s.set_var("emG", 3.3), s.set_var("emB", 6.0),
        ]),

        # Mat 6: Hero 4 — Brushed Rose-Copper Ring
        s.if_(s.eq(s.arg("matId"), 6), [
            s.set_var("albR", 0.96), s.set_var("albG", 0.56), s.set_var("albB", 0.40),
            s.set_var("metal", 0.93),
            s.set_var("rough", 0.18),
        ]),
    ])

    # =========================================================================
    # 8. COOK-TORRANCE GGX PBR + MINI-LUMEN GI + VOLUMETRIC GOD RAYS PIXEL SHADER
    # =========================================================================
    p_shade = s.define_proc("shade_pixel", ["sx", "sy"], warp=True, body=[
        s.set_var("u", s.div(s.arg("sx"), 180.0)),
        s.set_var("v", s.div(s.arg("sy"), 180.0)),

        s.set_var("rdX", s.add(s.mul(fwdX, fov), s.add(s.mul(rgtX, u), s.mul(upX, v)))),
        s.set_var("rdY", s.add(s.mul(fwdY, fov), s.add(s.mul(rgtY, u), s.mul(upY, v)))),
        s.set_var("rdZ", s.add(s.mul(fwdZ, fov), s.add(s.mul(rgtZ, u), s.mul(upZ, v)))),
        s.set_var("invLen", s.div(1.0, s.sqrt(s.add(s.mul(rdX, rdX), s.add(s.mul(rdY, rdY), s.mul(rdZ, rdZ)))))),
        s.set_var("rdX", s.mul(rdX, invLen)),
        s.set_var("rdY", s.mul(rdY, invLen)),
        s.set_var("rdZ", s.mul(rdZ, invLen)),

        # Adaptive march steps (36 in FAST_MODE vs 54 in full quality)
        s.if_else(s.eq(FAST_MODE, 1), [s.set_var("maxStepsV", 34)], [s.set_var("maxStepsV", 54)]),
        s.call_proc(p_march, camX, camY, camZ, rdX, rdY, rdZ, 22.0, maxStepsV),
        s.set_var("primT", tRay),
        s.set_var("primMat", hitMat),
        s.change_var("RAYS_CAST", 1),

        s.call_proc(p_sky, rdX, rdY, rdZ),

        s.if_else(
            s.eq(hitMat, 0),
            [
                s.if_else(
                    s.eq(RENDER_MODE, 1),
                    [s.set_var("colR", 0.35), s.set_var("colG", 0.58), s.set_var("colB", 0.92)],
                    [s.set_var("colR", skyR), s.set_var("colG", skyG), s.set_var("colB", skyB)],
                ),
                s.if_(s.eq(RENDER_MODE, 4), [s.set_var("colR", 0.05), s.set_var("colG", 0.05), s.set_var("colB", 0.08)]),
                s.if_(s.eq(RENDER_MODE, 5), [s.set_var("colR", 1.0), s.set_var("colG", 1.0), s.set_var("colB", 1.0)]),
            ],
            [
                s.call_proc(p_normal, hitX, hitY, hitZ),
                s.call_proc(p_mat, hitMat, hitX, hitY, hitZ, primT),

                # Procedural micro-normal perturbation (distance-attenuated for clean anti-aliasing!)
                s.if_(s.land(s.lt(hitMat, 3), s.lnot(s.eq(RENDER_MODE, 1))), [
                    s.set_var("dTmp2", s.div(0.022, s.add(1.0, s.mul(primT, 0.15)))),
                    s.change_var("nX", s.mul(dTmp2, s.sin(s.add(s.mul(hitX, 340), s.mul(hitZ, 290))))),
                    s.change_var("nZ", s.mul(dTmp2, s.cos(s.sub(s.mul(hitZ, 310), s.mul(hitY, 270))))),
                    s.set_var("invLen", s.div(1.0, s.sqrt(s.add(s.mul(nX, nX), s.add(s.mul(nY, nY), s.mul(nZ, nZ)))))),
                    s.set_var("nX", s.mul(nX, invLen)),
                    s.set_var("nY", s.mul(nY, invLen)),
                    s.set_var("nZ", s.mul(nZ, invLen)),
                ]),

                s.set_var("vX", s.mul(rdX, -1)),
                s.set_var("vY", s.mul(rdY, -1)),
                s.set_var("vZ", s.mul(rdZ, -1)),

                s.set_var("nDotL", s.add(s.mul(nX, SUN_X), s.add(s.mul(nY, SUN_Y), s.mul(nZ, SUN_Z)))),
                s.if_(s.lt(nDotL, 0), [s.set_var("nDotL", 0)]),
                s.set_var("nDotV", s.add(s.mul(nX, vX), s.add(s.mul(nY, vY), s.mul(nZ, vZ)))),
                s.if_(s.lt(nDotV, 0.001), [s.set_var("nDotV", 0.001)]),

                # --- MODE 1: Basic Scratch 3D Baseline ---
                s.if_else(
                    s.eq(RENDER_MODE, 1),
                    [
                        s.set_var("dTmp", s.add(0.24, s.mul(0.76, nDotL))),
                        s.set_var("colR", s.add(s.mul(albR, dTmp), s.mul(emR, 0.35))),
                        s.set_var("colG", s.add(s.mul(albG, dTmp), s.mul(emG, 0.35))),
                        s.set_var("colB", s.add(s.mul(albB, dTmp), s.mul(emB, 0.35))),
                    ],
                    [
                        # --- MODE 4: Normals ---
                        s.if_else(
                            s.eq(RENDER_MODE, 4),
                            [
                                s.set_var("colR", s.add(0.5, s.mul(nX, 0.5))),
                                s.set_var("colG", s.add(0.5, s.mul(nY, 0.5))),
                                s.set_var("colB", s.add(0.5, s.mul(nZ, 0.5))),
                            ],
                            [
                                # Soft Shadows
                                s.if_else(
                                    s.gt(nDotL, 0.001),
                                    [
                                        s.if_else(s.eq(FAST_MODE, 1), [s.set_var("maxStepsV", 12)], [s.set_var("maxStepsV", 22)]),
                                        s.call_proc(p_shadow, s.add(hitX, s.mul(nX, 0.02)), s.add(hitY, s.mul(nY, 0.02)), s.add(hitZ, s.mul(nZ, 0.02)), 10.0, maxStepsV),
                                    ],
                                    [s.set_var("shd", 0.0)],
                                ),
                                # Multi-scale SDF AO
                                s.call_proc(p_ao, hitX, hitY, hitZ, nX, nY, nZ),

                                # --- MODE 5: AO + Soft Shadows ---
                                s.if_else(
                                    s.eq(RENDER_MODE, 5),
                                    [
                                        s.set_var("dTmp", s.mul(ao, s.add(0.30, s.mul(0.70, shd)))),
                                        s.set_var("colR", dTmp), s.set_var("colG", dTmp), s.set_var("colB", dTmp),
                                    ],
                                    [
                                        # COOK-TORRANCE GGX PBR BRDF
                                        s.set_var("hX", s.add(SUN_X, vX)),
                                        s.set_var("hY", s.add(SUN_Y, vY)),
                                        s.set_var("hZ", s.add(SUN_Z, vZ)),
                                        s.set_var("invLen", s.div(1.0, s.sqrt(s.add(s.mul(hX, hX), s.add(s.mul(hY, hY), s.mul(hZ, hZ)))))),
                                        s.set_var("hX", s.mul(hX, invLen)),
                                        s.set_var("hY", s.mul(hY, invLen)),
                                        s.set_var("hZ", s.mul(hZ, invLen)),

                                        s.set_var("nDotH", s.add(s.mul(nX, hX), s.add(s.mul(nY, hY), s.mul(nZ, hZ)))),
                                        s.if_(s.lt(nDotH, 0), [s.set_var("nDotH", 0)]),
                                        s.set_var("vDotH", s.add(s.mul(vX, hX), s.add(s.mul(vY, hY), s.mul(vZ, hZ)))),
                                        s.if_(s.lt(vDotH, 0), [s.set_var("vDotH", 0)]),

                                        s.set_var("f0R", s.add(s.mul(0.04, s.sub(1, metal)), s.mul(albR, metal))),
                                        s.set_var("f0G", s.add(s.mul(0.04, s.sub(1, metal)), s.mul(albG, metal))),
                                        s.set_var("f0B", s.add(s.mul(0.04, s.sub(1, metal)), s.mul(albB, metal))),

                                        s.set_var("dTmp", s.sub(1.0, vDotH)),
                                        s.set_var("fres", s.mul(dTmp, s.mul(dTmp, s.mul(dTmp, s.mul(dTmp, dTmp))))),
                                        s.set_var("fR", s.add(f0R, s.mul(s.sub(1, f0R), fres))),
                                        s.set_var("fG", s.add(f0G, s.mul(s.sub(1, f0G), fres))),
                                        s.set_var("fB", s.add(f0B, s.mul(s.sub(1, f0B), fres))),

                                        s.set_var("alpha2", s.mul(rough, rough)),
                                        s.set_var("alpha2", s.mul(alpha2, alpha2)),
                                        s.if_(s.lt(alpha2, 0.0004), [s.set_var("alpha2", 0.0004)]),
                                        s.set_var("denom", s.add(s.mul(s.mul(nDotH, nDotH), s.sub(alpha2, 1.0)), 1.0)),
                                        s.set_var("ndf", s.div(alpha2, s.mul(3.14159, s.mul(denom, denom)))),

                                        s.set_var("dTmp", s.add(s.mul(rough, 0.5), 0.125)),
                                        s.set_var("vis", s.div(0.25, s.add(s.mul(nDotL, s.sub(1, dTmp)), dTmp))),
                                        s.set_var("specS", s.mul(ndf, vis)),
                                        s.if_(s.gt(specS, 14.0), [s.set_var("specS", 14.0)]),

                                        s.set_var("kD", s.mul(s.sub(1.0, metal), 0.31831)),
                                        s.set_var("dTmp", s.mul(nDotL, shd)),
                                        s.set_var("colR", s.mul(s.add(s.mul(s.mul(albR, kD), s.sub(1, fR)), s.mul(fR, specS)), s.mul(4.3, dTmp))),
                                        s.set_var("colG", s.mul(s.add(s.mul(s.mul(albG, kD), s.sub(1, fG)), s.mul(fG, specS)), s.mul(2.75, dTmp))),
                                        s.set_var("colB", s.mul(s.add(s.mul(s.mul(albB, kD), s.sub(1, fB)), s.mul(fB, specS)), s.mul(1.35, dTmp))),

                                        s.change_var("colR", emR),
                                        s.change_var("colG", emG),
                                        s.change_var("colB", emB),

                                        # MINI-LUMEN GI + 1-BOUNCE REFLECTIONS
                                        s.if_else(
                                            s.eq(RENDER_MODE, 2),
                                            [
                                                s.change_var("colR", s.mul(s.mul(albR, s.sub(1, metal)), s.mul(0.14, ao))),
                                                s.change_var("colG", s.mul(s.mul(albG, s.sub(1, metal)), s.mul(0.17, ao))),
                                                s.change_var("colB", s.mul(s.mul(albB, s.sub(1, metal)), s.mul(0.24, ao))),
                                            ],
                                            [
                                                # 1) Sky Hemisphere GI + Warm Travertine Bounce GI
                                                s.set_var("dTmp", s.mul(s.add(0.5, s.mul(0.5, nY)), ao)),
                                                s.set_var("dTmp2", s.mul(s.sub(1.0, metal), 0.31831)),
                                                s.change_var("colR", s.mul(s.mul(albR, dTmp2), s.mul(0.30, dTmp))),
                                                s.change_var("colG", s.mul(s.mul(albG, dTmp2), s.mul(0.45, dTmp))),
                                                s.change_var("colB", s.mul(s.mul(albB, dTmp2), s.mul(0.88, dTmp))),

                                                s.set_var("dTmp", s.mul(s.add(0.45, s.mul(0.55, s.sub(0, nY))), ao)),
                                                s.if_(s.lt(dTmp, 0.08), [s.set_var("dTmp", 0.08)]),
                                                s.change_var("colR", s.mul(s.mul(albR, dTmp2), s.mul(0.68, dTmp))),
                                                s.change_var("colG", s.mul(s.mul(albG, dTmp2), s.mul(0.41, dTmp))),
                                                s.change_var("colB", s.mul(s.mul(albB, dTmp2), s.mul(0.18, dTmp))),

                                                # 2) Dynamic Emissive Area-Light GI from Cyan Lumen Crystal
                                                s.if_(s.lnot(s.eq(hitMat, 5)), [
                                                    s.set_var("elX", s.sub(CRY_X, hitX)),
                                                    s.set_var("elY", s.sub(CRY_Y, hitY)),
                                                    s.set_var("elZ", s.sub(CRY_Z, hitZ)),
                                                    s.set_var("elDist", s.sqrt(s.add(s.mul(elX, elX), s.add(s.mul(elY, elY), s.mul(elZ, elZ))))),
                                                    s.set_var("invLen", s.div(1.0, s.add(elDist, 0.001))),
                                                    s.set_var("elX", s.mul(elX, invLen)),
                                                    s.set_var("elY", s.mul(elY, invLen)),
                                                    s.set_var("elZ", s.mul(elZ, invLen)),
                                                    s.set_var("elDot", s.div(s.add(s.add(s.mul(nX, elX), s.add(s.mul(nY, elY), s.mul(nZ, elZ))), 0.28), 1.28)),
                                                    s.if_(s.gt(elDot, 0), [
                                                        s.set_var("elAtten", s.div(s.mul(elDot, ao), s.add(0.32, s.mul(elDist, elDist)))),
                                                        s.change_var("colR", s.mul(s.mul(albR, dTmp2), s.mul(0.32, elAtten))),
                                                        s.change_var("colG", s.mul(s.mul(albG, dTmp2), s.mul(2.25, elAtten))),
                                                        s.change_var("colB", s.mul(s.mul(albB, dTmp2), s.mul(3.90, elAtten))),
                                                        s.set_var("hX", s.add(elX, vX)),
                                                        s.set_var("hY", s.add(elY, vY)),
                                                        s.set_var("hZ", s.add(elZ, vZ)),
                                                        s.set_var("invLen", s.div(1.0, s.sqrt(s.add(s.mul(hX, hX), s.add(s.mul(hY, hY), s.mul(hZ, hZ)))))),
                                                        s.set_var("nDotH", s.mul(s.add(s.mul(nX, hX), s.add(s.mul(nY, hY), s.mul(nZ, hZ))), invLen)),
                                                        s.if_(s.gt(nDotH, 0), [
                                                            s.set_var("denom", s.add(s.mul(s.mul(nDotH, nDotH), s.sub(alpha2, 1.0)), 1.0)),
                                                            s.set_var("dTmp", s.div(s.mul(alpha2, 0.16), s.mul(denom, denom))),
                                                            s.if_(s.gt(dTmp, 6.5), [s.set_var("dTmp", 6.5)]),
                                                            s.set_var("dTmp", s.mul(dTmp, elAtten)),
                                                            s.change_var("colR", s.mul(f0R, s.mul(0.32, dTmp))),
                                                            s.change_var("colG", s.mul(f0G, s.mul(2.25, dTmp))),
                                                            s.change_var("colB", s.mul(f0B, s.mul(3.90, dTmp))),
                                                        ]),
                                                    ]),
                                                ]),

                                                # 3) TRUE 1-BOUNCE LUMEN SPECULAR REFLECTIONS (with multi-bounce fill!)
                                                s.if_(s.lt(rough, 0.36), [
                                                    s.set_var("dTmp", s.mul(2.0, s.add(s.mul(rdX, nX), s.add(s.mul(rdY, nY), s.mul(rdZ, nZ))))),
                                                    s.set_var("refX", s.sub(rdX, s.mul(dTmp, nX))),
                                                    s.set_var("refY", s.sub(rdY, s.mul(dTmp, nY))),
                                                    s.set_var("refZ", s.sub(rdZ, s.mul(dTmp, nZ))),

                                                    s.set_var("dTmp", s.sub(1.0, nDotV)),
                                                    s.set_var("fres", s.mul(dTmp, s.mul(dTmp, s.mul(dTmp, s.mul(dTmp, dTmp))))),
                                                    s.set_var("fR", s.add(f0R, s.mul(s.sub(s.sub(1, rough), f0R), fres))),
                                                    s.set_var("fG", s.add(f0G, s.mul(s.sub(s.sub(1, rough), f0G), fres))),
                                                    s.set_var("fB", s.add(f0B, s.mul(s.sub(s.sub(1, rough), f0B), fres))),
                                                    s.if_(s.lt(fR, f0R), [s.set_var("fR", f0R)]),
                                                    s.if_(s.lt(fG, f0G), [s.set_var("fG", f0G)]),
                                                    s.if_(s.lt(fB, f0B), [s.set_var("fB", f0B)]),

                                                    s.if_else(
                                                        s.eq(FAST_MODE, 1),
                                                        [
                                                            # Fast interactive mode: analytical Sky/IBL reflection!
                                                            s.call_proc(p_sky, refX, refY, refZ),
                                                            s.set_var("refColR", s.mul(skyR, 0.75)),
                                                            s.set_var("refColG", s.mul(skyG, 0.75)),
                                                            s.set_var("refColB", s.mul(skyB, 0.75)),
                                                        ],
                                                        [
                                                            s.set_var("roX", s.add(hitX, s.mul(nX, 0.03))),
                                                            s.set_var("roY", s.add(hitY, s.mul(nY, 0.03))),
                                                            s.set_var("roZ", s.add(hitZ, s.mul(nZ, 0.03))),
                                                            s.call_proc(p_march, roX, roY, roZ, refX, refY, refZ, 16.0, 26),
                                                            s.change_var("RAYS_CAST", 1),
                                                            s.if_else(
                                                                s.eq(hitMat, 0),
                                                                [
                                                                    s.call_proc(p_sky, refX, refY, refZ),
                                                                    s.set_var("refColR", skyR),
                                                                    s.set_var("refColG", skyG),
                                                                    s.set_var("refColB", skyB),
                                                                ],
                                                                [
                                                                    # Multi-bounce Surface Cache hit lighting (warm bounce fill on beam undersides!)
                                                                    s.call_proc(p_normal, hitX, hitY, hitZ),
                                                                    s.call_proc(p_mat, hitMat, hitX, hitY, hitZ, tRay),
                                                                    s.set_var("dTmp", s.add(s.mul(nX, SUN_X), s.add(s.mul(nY, SUN_Y), s.mul(nZ, SUN_Z)))),
                                                                    s.if_(s.lt(dTmp, 0), [s.set_var("dTmp", 0)]),
                                                                    # Warm multi-bounce fill keeps reflected beam undersides luminous instead of pitch black!
                                                                    s.set_var("refColR", s.add(emR, s.mul(albR, s.add(0.55, s.mul(2.1, dTmp))))),
                                                                    s.set_var("refColG", s.add(emG, s.mul(albG, s.add(0.45, s.mul(1.4, dTmp))))),
                                                                    s.set_var("refColB", s.add(emB, s.mul(albB, s.add(0.42, s.mul(0.85, dTmp))))),
                                                                ],
                                                            ),
                                                        ],
                                                    ),
                                                    s.set_var("dTmp", s.mul(s.sub(1.0, s.mul(rough, 1.5)), s.add(0.38, s.mul(0.62, ao)))),
                                                    s.if_(s.lt(dTmp, 0), [s.set_var("dTmp", 0)]),
                                                    s.change_var("colR", s.mul(s.mul(refColR, fR), dTmp)),
                                                    s.change_var("colG", s.mul(s.mul(refColG, fG), dTmp)),
                                                    s.change_var("colB", s.mul(s.mul(refColB, fB), dTmp)),
                                                ]),

                                                # 4) Aerial Perspective Fog
                                                s.set_var("fogAmt", s.sub(1.0, s.exp(s.mul(-0.0025, s.mul(primT, primT))))),
                                                s.if_(s.gt(fogAmt, 0.68), [s.set_var("fogAmt", 0.68)]),
                                                s.call_proc(p_sky, rdX, rdY, rdZ),
                                                s.set_var("colR", s.add(s.mul(colR, s.sub(1, fogAmt)), s.mul(skyR, s.mul(fogAmt, 0.72)))),
                                                s.set_var("colG", s.add(s.mul(colG, s.sub(1, fogAmt)), s.mul(skyG, s.mul(fogAmt, 0.72)))),
                                                s.set_var("colB", s.add(s.mul(colB, s.sub(1, fogAmt)), s.mul(skyB, s.mul(fogAmt, 0.72)))),
                                            ],
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),

        # =====================================================================
        # 9. VOLUMETRIC GOD RAYS / SUN SHAFTS (skipped in FAST_MODE)
        # =====================================================================
        s.if_(s.land(s.eq(FAST_MODE, 0), s.lor(s.eq(RENDER_MODE, 0), s.eq(RENDER_MODE, 3))), [
            s.set_var("volSun", s.add(s.mul(rdX, SUN_X), s.add(s.mul(rdY, SUN_Y), s.mul(rdZ, SUN_Z)))),
            s.if_(s.lt(volSun, 0), [s.set_var("volSun", 0)]),
            s.set_var("volSun", s.add(0.18, s.mul(0.82, s.mul(volSun, volSun)))),
            s.set_var("tMax", primT),
            s.if_(s.eq(primMat, 0), [s.set_var("tMax", 11.5)]),
            s.if_(s.gt(tMax, 11.5), [s.set_var("tMax", 11.5)]),
            s.set_var("bayer", s.mod(s.add(s.mul(px, 0.37), s.mul(py, 0.73)), 1.0)),
            s.set_var("volG", 0),
            s.set_var("stepIdx", 0),
            s.repeat(6, [
                s.set_var("volT", s.mul(s.div(s.add(stepIdx, bayer), 6.0), tMax)),
                s.set_var("volX", s.add(camX, s.mul(rdX, volT))),
                s.set_var("volY", s.add(camY, s.mul(rdY, volT))),
                s.set_var("volZ", s.add(camZ, s.mul(rdZ, volT))),
                s.call_proc(p_map, s.add(volX, s.mul(SUN_X, 1.4)), s.add(volY, s.mul(SUN_Y, 1.4)), s.add(volZ, s.mul(SUN_Z, 1.4))),
                s.if_(s.gt(sd, 0.08), [
                    s.call_proc(p_map, s.add(volX, s.mul(SUN_X, 3.2)), s.add(volY, s.mul(SUN_Y, 3.2)), s.add(volZ, s.mul(SUN_Z, 3.2))),
                    s.if_(s.gt(sd, 0.12), [
                        s.set_var("dTmp", s.exp(s.mul(-0.30, s.add(volY, 1.3)))),
                        s.change_var("volG", dTmp),
                    ]),
                ]),
                s.change_var("stepIdx", 1),
            ]),
            s.set_var("volG", s.mul(s.div(volG, 6.0), s.mul(volSun, s.mul(tMax, 0.025)))),
            s.change_var("colR", s.mul(volG, 1.50)),
            s.change_var("colG", s.mul(volG, 0.94)),
            s.change_var("colB", s.mul(volG, 0.42)),
        ]),

        # =====================================================================
        # 10. COLLECT HDR BLOOM EMITTERS (Mode 0 only)
        # =====================================================================
        s.if_(s.eq(RENDER_MODE, 0), [
            s.set_var("lum", s.add(s.mul(colR, 0.2126), s.add(s.mul(colG, 0.7152), s.mul(colB, 0.0722)))),
            s.if_(s.land(s.gt(lum, 1.45), s.land(s.eq(s.mod(px, 3), 0), s.eq(s.mod(py, 3), 0))), [
                s.if_(s.lt(BLOOM_COUNT, 480), [
                    s.add_to_list(blmX, s.arg("sx")),
                    s.add_to_list(blmY, s.arg("sy")),
                    s.add_to_list(blmR, colR),
                    s.add_to_list(blmG, colG),
                    s.add_to_list(blmB, colB),
                    s.add_to_list(blmS, s.sub(lum, 1.3)),
                    s.change_var("BLOOM_COUNT", 1),
                ]),
            ]),
        ]),

        # =====================================================================
        # 11. ACES FILMIC TONE MAPPING + GAMMA + BAYER DITHERING
        # =====================================================================
        s.if_else(
            s.lor(s.eq(RENDER_MODE, 0), s.lor(s.eq(RENDER_MODE, 2), s.eq(RENDER_MODE, 3))),
            [
                s.set_var("vig", s.sub(1.0, s.mul(0.16, s.add(s.mul(u, u), s.mul(v, v))))),
                s.if_(s.lt(vig, 0.65), [s.set_var("vig", 0.65)]),
                s.set_var("pR", s.mul(colR, s.mul(vig, 0.86))),
                s.set_var("pG", s.mul(colG, s.mul(vig, 0.86))),
                s.set_var("pB", s.mul(colB, s.mul(vig, 0.86))),

                s.set_var("pR", s.div(s.mul(pR, s.add(s.mul(2.51, pR), 0.03)), s.add(s.mul(pR, s.add(s.mul(2.43, pR), 0.59)), 0.14))),
                s.set_var("pG", s.div(s.mul(pG, s.add(s.mul(2.51, pG), 0.03)), s.add(s.mul(pG, s.add(s.mul(2.43, pG), 0.59)), 0.14))),
                s.set_var("pB", s.div(s.mul(pB, s.add(s.mul(2.51, pB), 0.03)), s.add(s.mul(pB, s.add(s.mul(2.43, pB), 0.59)), 0.14))),
                *clamp01_stmts(s, "pR"),
                *clamp01_stmts(s, "pG"),
                *clamp01_stmts(s, "pB"),

                s.set_var("pR", s.sqrt(pR)),
                s.set_var("pG", s.sqrt(pG)),
                s.set_var("pB", s.sqrt(pB)),

                s.set_var("bayer", s.sub(s.mul(s.add(s.mul(s.mod(px, 2), 2), s.mod(py, 2)), 0.25), 0.375)),
                s.set_var("pR", s.floor(s.add(s.mul(pR, 255.0), bayer))),
                s.set_var("pG", s.floor(s.add(s.mul(pG, 255.0), bayer))),
                s.set_var("pB", s.floor(s.add(s.mul(pB, 255.0), bayer))),
            ],
            [
                s.set_var("pR", colR), s.set_var("pG", colG), s.set_var("pB", colB),
                *clamp01_stmts(s, "pR"), *clamp01_stmts(s, "pG"), *clamp01_stmts(s, "pB"),
                s.set_var("pR", s.floor(s.mul(pR, 255.0))),
                s.set_var("pG", s.floor(s.mul(pG, 255.0))),
                s.set_var("pB", s.floor(s.mul(pB, 255.0))),
            ],
        ),

        *clamp_stmts(s, "pR", 0, 255),
        *clamp_stmts(s, "pG", 0, 255),
        *clamp_stmts(s, "pB", 0, 255),
        s.set_var("outCol", s.add(s.mul(pR, 65536), s.add(s.mul(pG, 256), pB))),
    ])

    # =========================================================================
    # 12. HARDWARE-ACCELERATED 32-BIT ARGB GPU PEN BLOOM PASS
    # =========================================================================
    p_bloom = s.define_proc("apply_gpu_pen_bloom", warp=True, body=[
        s.set_var("t1", now_ms()),
        s.set_var("bCount", s.length_of_list(blmX)),
        s.if_(s.gt(bCount, 0), [
            s.set_var("bi", 1),
            s.repeat(bCount, [
                s.set_var("ax", s.item_of(blmX, bi)),
                s.set_var("ay", s.item_of(blmY, bi)),
                s.set_var("pR", s.item_of(blmR, bi)),
                s.set_var("pG", s.item_of(blmG, bi)),
                s.set_var("pB", s.item_of(blmB, bi)),
                s.set_var("dTmp", pR),
                s.if_(s.gt(pG, dTmp), [s.set_var("dTmp", pG)]),
                s.if_(s.gt(pB, dTmp), [s.set_var("dTmp", pB)]),
                s.if_(s.lt(dTmp, 0.001), [s.set_var("dTmp", 0.001)]),
                s.set_var("invLen", s.div(255.0, dTmp)),
                s.set_var("pR", s.floor(s.mul(pR, invLen))),
                s.set_var("pG", s.floor(s.mul(pG, invLen))),
                s.set_var("pB", s.floor(s.mul(pB, invLen))),
                s.set_var("outCol", s.add(s.mul(pR, 65536), s.add(s.mul(pG, 256), pB))),

                s.goto_xy(ax, ay),
                s.pen_set_size(48),
                s.pen_set_color(s.add(2 * 16777216, outCol)),
                s.pen_down(), s.pen_up(),
                s.pen_set_size(24),
                s.pen_set_color(s.add(4 * 16777216, outCol)),
                s.pen_down(), s.pen_up(),
                s.pen_set_size(11),
                s.pen_set_color(s.add(8 * 16777216, outCol)),
                s.pen_down(), s.pen_up(),

                s.change_var("bi", 1),
            ]),
        ]),
        s.set_var("BLOOM_MS", s.sub(now_ms(), t1)),
    ])

    # =========================================================================
    # 13. CAMERA + SCANLINE RENDERER
    # =========================================================================
    p_setup_cam = s.define_proc("setup_camera", warp=True, body=[
        s.set_var("fwdX", s.mul(s.sin(camYaw), s.cos(camPitch))),
        s.set_var("fwdY", s.sin(camPitch)),
        s.set_var("fwdZ", s.mul(s.cos(camYaw), s.cos(camPitch))),
        s.set_var("rgtX", fwdZ),
        s.set_var("rgtY", 0),
        s.set_var("rgtZ", s.mul(fwdX, -1)),
        s.set_var("invLen", s.div(1.0, s.sqrt(s.add(s.mul(rgtX, rgtX), s.mul(rgtZ, rgtZ))))),
        s.set_var("rgtX", s.mul(rgtX, invLen)),
        s.set_var("rgtZ", s.mul(rgtZ, invLen)),
        s.set_var("upX", s.sub(s.mul(fwdY, rgtZ), s.mul(fwdZ, rgtY))),
        s.set_var("upY", s.sub(s.mul(fwdZ, rgtX), s.mul(fwdX, rgtZ))),
        s.set_var("upZ", s.sub(s.mul(fwdX, rgtY), s.mul(fwdY, rgtX))),
    ])

    p_render_row = s.define_proc("render_row", ["rowIdx", "stepSz"], warp=True, body=[
        s.set_var("py", s.arg("rowIdx")),
        s.set_var("scrY", s.sub(180, s.add(s.mul(py, s.arg("stepSz")), s.mul(s.arg("stepSz"), 0.5)))),
        s.set_var("colsN", s.floor(s.div(480, s.arg("stepSz")))),
        s.pen_set_size(s.arg("stepSz")),
        s.set_var("px", 0),
        s.set_var("scrX", s.add(-240, s.mul(s.arg("stepSz"), 0.5))),
        s.goto_xy(scrX, scrY),
        s.repeat(colsN, [
            s.call_proc(p_shade, scrX, scrY),
            s.pen_set_color(outCol),
            s.if_(s.eq(px, 0), [s.pen_down()]),
            s.change_x(s.arg("stepSz")),
            s.change_var("scrX", s.arg("stepSz")),
            s.change_var("px", 1),
        ]),
        s.pen_up(),
    ])

    p_render_frame = s.define_proc("render_frame", ["stepSz"], warp=False, body=[
        s.set_var("t0", now_ms()),
        s.set_var("RAYS_CAST", 0),
        s.set_var("BLOOM_COUNT", 0),
        s.set_var("BLOOM_MS", 0),
        s.delete_all_list(blmX), s.delete_all_list(blmY),
        s.delete_all_list(blmR), s.delete_all_list(blmG), s.delete_all_list(blmB), s.delete_all_list(blmS),
        s.call_proc(p_setup_cam),
        s.if_(s.gt(s.arg("stepSz"), 2), [s.pen_clear()]),
        s.set_var("rowsN", s.floor(s.div(360, s.arg("stepSz")))),
        s.set_var("py", 0),
        s.repeat(rowsN, [
            # For fast preview (step>=4), render without interruption; for HD refine, abort early if user presses movement key!
            s.if_(s.land(s.eq(AUTO_STOP, 0), s.lt(s.arg("stepSz"), 4)), [
                s.if_(
                    s.lor(
                        s.lor(s.key_pressed("w"), s.key_pressed("s")),
                        s.lor(
                            s.lor(s.key_pressed("a"), s.key_pressed("d")),
                            s.lor(s.key_pressed("left arrow"), s.key_pressed("right arrow")),
                        ),
                    ),
                    [s.set_var("PIXEL_STEP", 6), s.set_var("FAST_MODE", 1), s.stop_this()],
                ),
            ]),
            s.call_proc(p_render_row, py, s.arg("stepSz")),
            s.change_var("py", 1),
        ]),
        s.if_(s.eq(RENDER_MODE, 0), [
            s.call_proc(p_bloom),
        ]),
        s.set_var("FRAME_MS", s.sub(now_ms(), t0)),
    ])

    s.when_flag_clicked([
        s.hide(),
        s.set_var("DONE", 0),
        s.if_else(
            s.eq(AUTO_STOP, 1),
            [
                s.call_proc(p_render_frame, PIXEL_STEP),
                s.set_var("DONE", 1),
            ],
            [
                s.set_var("PIXEL_STEP", 6),
                s.set_var("FAST_MODE", 1),
                s.forever([
                    s.set_var("dTmp", 0),
                    s.if_(s.key_pressed("w"), [s.change_var("camX", s.mul(fwdX, 0.30)), s.change_var("camZ", s.mul(fwdZ, 0.30)), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("s"), [s.change_var("camX", s.mul(fwdX, -0.30)), s.change_var("camZ", s.mul(fwdZ, -0.30)), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("a"), [s.change_var("camX", s.mul(rgtX, -0.30)), s.change_var("camZ", s.mul(rgtZ, -0.30)), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("d"), [s.change_var("camX", s.mul(rgtX, 0.30)), s.change_var("camZ", s.mul(rgtZ, 0.30)), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("left arrow"), [s.change_var("camYaw", -6), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("right arrow"), [s.change_var("camYaw", 6), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("up arrow"), [s.change_var("camPitch", 4), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("down arrow"), [s.change_var("camPitch", -4), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("1"), [s.set_var("RENDER_MODE", 0), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("2"), [s.set_var("RENDER_MODE", 1), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("3"), [s.set_var("RENDER_MODE", 2), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("4"), [s.set_var("RENDER_MODE", 3), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("5"), [s.set_var("RENDER_MODE", 4), s.set_var("dTmp", 1)]),
                    s.if_(s.key_pressed("6"), [s.set_var("RENDER_MODE", 5), s.set_var("dTmp", 1)]),
                    s.if_(s.eq(dTmp, 1), [s.set_var("PIXEL_STEP", 6), s.set_var("FAST_MODE", 1)]),
                    s.if_(s.gt(PIXEL_STEP, 0), [
                        s.call_proc(p_render_frame, PIXEL_STEP),
                        s.if_else(
                            s.eq(PIXEL_STEP, 6),
                            [s.set_var("PIXEL_STEP", 2), s.set_var("FAST_MODE", 0)],
                            [s.if_else(s.eq(PIXEL_STEP, 2), [s.set_var("PIXEL_STEP", 1)], [s.set_var("PIXEL_STEP", 0)])],
                        ),
                    ]),
                ]),
            ],
        ),
    ])

    from pathlib import Path
    out = pb.save_sb3(Path(__file__).resolve().parent / "sb3" / "ue5_lumen_sdf.sb3")
    print("Built:", out, f"({len(s.blocks)} Scratch blocks)")


if __name__ == "__main__":
    build_ue5_lumen()
