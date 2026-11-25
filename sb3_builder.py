"""
sb3_builder.py — Programmatic Vanilla Scratch 3.0 (.sb3) Compiler/DSL.

Generates 100% standard Scratch 3.0 project.json + .sb3 archives (Pen extension only,
zero non-standard TurboWarp extensions) so every generated project runs identically
on official scratch.mit.edu AND TurboWarp.
"""

import hashlib
import json
import zipfile
from pathlib import Path

EMPTY_SVG = (
    '<svg version="1.1" xmlns="http://www.w3.org/2000/svg" '
    'width="1" height="1" viewBox="0 0 1 1"></svg>'
)
EMPTY_SVG_MD5 = hashlib.md5(EMPTY_SVG.encode("utf-8")).hexdigest()


def make_radial_glow_svg(size=64):
    """Optional soft radial glow SVG costume (for comparing Pen-only vs Pen+Stamp)."""
    r = size / 2
    svg = (
        f'<svg version="1.1" xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<defs><radialGradient id="g" cx="50%" cy="50%" r="50%">'
        f'<stop offset="0%" stop-color="#ffffff" stop-opacity="1"/>'
        f'<stop offset="30%" stop-color="#ffffff" stop-opacity="0.6"/>'
        f'<stop offset="65%" stop-color="#ffffff" stop-opacity="0.18"/>'
        f'<stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>'
        f'</radialGradient></defs>'
        f'<circle cx="{r}" cy="{r}" r="{r}" fill="url(#g)"/></svg>'
    )
    return svg, hashlib.md5(svg.encode("utf-8")).hexdigest()


class Expr:
    """Represents a Scratch reporter/boolean expression or literal."""
    def __init__(self, kind, val=None):
        self.kind = kind  # 'num', 'str', 'var', 'arg', 'block'
        self.val = val


class SpriteBuilder:
    def __init__(self, name="Renderer", is_stage=False):
        self.name = name
        self.is_stage = is_stage
        self.variables = {}  # name -> (id, init_val)
        self.lists = {}      # name -> (id, init_list)
        self.blocks = {}     # block_id -> block_dict
        self.costumes = []
        self._id_counter = 0
        self._extra_assets = {}  # md5ext -> bytes

        # Always add a 1x1 transparent empty costume (optimal for Pen sprites!)
        self.add_svg_costume("blank", EMPTY_SVG, rot_x=0, rot_y=0)

    def add_svg_costume(self, name, svg_str, rot_x=0, rot_y=0):
        data = svg_str.encode("utf-8")
        md5 = hashlib.md5(data).hexdigest()
        md5ext = f"{md5}.svg"
        self._extra_assets[md5ext] = data
        self.costumes.append({
            "name": name,
            "bitmapResolution": 1,
            "dataFormat": "svg",
            "assetId": md5,
            "md5ext": md5ext,
            "rotationCenterX": rot_x,
            "rotationCenterY": rot_y,
        })

    def _uid(self, prefix="b"):
        self._id_counter += 1
        return f"{prefix}{self._id_counter}"

    def var(self, name, init=0):
        if name not in self.variables:
            vid = f"v_{self.name}_{name}"
            self.variables[name] = (vid, init)
        return Expr("var", name)

    def lst(self, name, init=None):
        if name not in self.lists:
            lid = f"l_{self.name}_{name}"
            self.lists[name] = (lid, list(init) if init is not None else [])
        return name

    def _ensure_var(self, name):
        if name not in self.variables:
            self.var(name, 0)
        return self.variables[name][0]

    def _ensure_list(self, name):
        if name not in self.lists:
            self.lst(name, [])
        return self.lists[name][0]

    def _add_block(self, opcode, inputs=None, fields=None, mutation=None, shadow=False, top_level=False):
        bid = self._uid("b")
        blk = {
            "opcode": opcode,
            "next": None,
            "parent": None,
            "inputs": inputs or {},
            "fields": fields or {},
            "shadow": shadow,
            "topLevel": top_level,
        }
        if top_level:
            blk["x"] = 0
            blk["y"] = 0
        if mutation is not None:
            blk["mutation"] = mutation
        self.blocks[bid] = blk
        return bid

    def _emit_input(self, val, parent_id, is_bool=False, is_color=False):
        """Convert Python value or Expr into a Scratch block input array."""
        if isinstance(val, (int, float)):
            if is_color:
                return [1, [4, str(val)]]
            return [1, [4, str(val)]]
        if isinstance(val, str):
            return [1, [10, val]]
        if isinstance(val, Expr):
            if val.kind == "var":
                vid = self._ensure_var(val.val)
                return [3, [12, val.val, vid], [10, "0"]]
            if val.kind == "arg":
                bid = self._add_block("argument_reporter_string_number", fields={"VALUE": [val.val, None]})
                self.blocks[bid]["parent"] = parent_id
                return [3, bid, [10, "0"]]
            if val.kind == "block":
                bid = val.val(parent_id)
                self.blocks[bid]["parent"] = parent_id
                if is_bool:
                    return [2, bid]
                return [3, bid, [10, "0"]]
        raise TypeError(f"Unsupported input: {val!r}")

    # --- Reporter builders ---
    def num(self, x):
        return x

    def arg(self, name):
        return Expr("arg", name)

    def _binop(self, opcode, k1, a, k2, b, is_bool=False):
        def build(parent_id):
            bid = self._add_block(opcode)
            self.blocks[bid]["inputs"][k1] = self._emit_input(a, bid, is_bool=is_bool)
            self.blocks[bid]["inputs"][k2] = self._emit_input(b, bid, is_bool=is_bool)
            return bid
        return Expr("block", build)

    def add(self, a, b): return self._binop("operator_add", "NUM1", a, "NUM2", b)
    def sub(self, a, b): return self._binop("operator_subtract", "NUM1", a, "NUM2", b)
    def mul(self, a, b): return self._binop("operator_multiply", "NUM1", a, "NUM2", b)
    def div(self, a, b): return self._binop("operator_divide", "NUM1", a, "NUM2", b)
    def mod(self, a, b): return self._binop("operator_mod", "NUM1", a, "NUM2", b)
    def rand(self, a, b): return self._binop("operator_random", "FROM", a, "TO", b)
    def lt(self, a, b): return self._binop("operator_lt", "OPERAND1", a, "OPERAND2", b)
    def gt(self, a, b): return self._binop("operator_gt", "OPERAND1", a, "OPERAND2", b)
    def eq(self, a, b): return self._binop("operator_equals", "OPERAND1", a, "OPERAND2", b)
    def land(self, a, b): return self._binop("operator_and", "OPERAND1", a, "OPERAND2", b, is_bool=True)
    def lor(self, a, b): return self._binop("operator_or", "OPERAND1", a, "OPERAND2", b, is_bool=True)
    def join(self, a, b): return self._binop("operator_join", "STRING1", a, "STRING2", b)

    def lnot(self, a):
        def build(parent_id):
            bid = self._add_block("operator_not")
            self.blocks[bid]["inputs"]["OPERAND"] = self._emit_input(a, bid, is_bool=True)
            return bid
        return Expr("block", build)

    def mathop(self, op, a):
        # op: 'abs','floor','ceiling','sqrt','sin','cos','tan','asin','acos','atan','ln','log','e ^','10 ^'
        def build(parent_id):
            bid = self._add_block("operator_mathop", fields={"OPERATOR": [op, None]})
            self.blocks[bid]["inputs"]["NUM"] = self._emit_input(a, bid)
            return bid
        return Expr("block", build)

    def round_(self, a):
        def build(parent_id):
            bid = self._add_block("operator_round")
            self.blocks[bid]["inputs"]["NUM"] = self._emit_input(a, bid)
            return bid
        return Expr("block", build)

    def abs_(self, a): return self.mathop("abs", a)
    def floor(self, a): return self.mathop("floor", a)
    def ceil(self, a): return self.mathop("ceiling", a)
    def sqrt(self, a): return self.mathop("sqrt", a)
    def sin(self, a): return self.mathop("sin", a)  # NOTE: degrees in Scratch!
    def cos(self, a): return self.mathop("cos", a)  # NOTE: degrees in Scratch!
    def tan(self, a): return self.mathop("tan", a)
    def atan(self, a): return self.mathop("atan", a)
    def ln(self, a): return self.mathop("ln", a)
    def exp(self, a): return self.mathop("e ^", a)
    def pow_(self, base, exp_val):
        # Scratch has no pow block! base^exp = e^(exp * ln(base))
        return self.exp(self.mul(exp_val, self.ln(base)))

    def timer(self):
        def build(parent_id):
            return self._add_block("sensing_timer")
        return Expr("block", build)

    def days_since_2000(self):
        def build(parent_id):
            return self._add_block("sensing_dayssince2000")
        return Expr("block", build)

    def key_pressed(self, key_name):
        def build(parent_id):
            bid = self._add_block("sensing_keypressed")
            mid = self._add_block("sensing_keyoptions", fields={"KEY_OPTION": [key_name, None]}, shadow=True)
            self.blocks[mid]["parent"] = bid
            self.blocks[bid]["inputs"]["KEY_OPTION"] = [1, mid]
            return bid
        return Expr("block", build)

    def mouse_down(self):
        def build(parent_id):
            return self._add_block("sensing_mousedown")
        return Expr("block", build)

    def mouse_x(self):
        def build(parent_id):
            return self._add_block("sensing_mousex")
        return Expr("block", build)

    def mouse_y(self):
        def build(parent_id):
            return self._add_block("sensing_mousey")
        return Expr("block", build)

    def item_of(self, list_name, idx):
        lid = self._ensure_list(list_name)
        def build(parent_id):
            bid = self._add_block("data_itemoflist", fields={"LIST": [list_name, lid]})
            self.blocks[bid]["inputs"]["INDEX"] = self._emit_input(idx, bid)
            return bid
        return Expr("block", build)

    def length_of_list(self, list_name):
        lid = self._ensure_list(list_name)
        def build(parent_id):
            return self._add_block("data_lengthoflist", fields={"LIST": [list_name, lid]})
        return Expr("block", build)

    # --- Statement builders ---
    def set_var(self, name, val):
        vid = self._ensure_var(name)
        bid = self._add_block("data_setvariableto", fields={"VARIABLE": [name, vid]})
        self.blocks[bid]["inputs"]["VALUE"] = self._emit_input(val, bid)
        return bid

    def change_var(self, name, val):
        vid = self._ensure_var(name)
        bid = self._add_block("data_changevariableby", fields={"VARIABLE": [name, vid]})
        self.blocks[bid]["inputs"]["VALUE"] = self._emit_input(val, bid)
        return bid

    def delete_all_list(self, list_name):
        lid = self._ensure_list(list_name)
        return self._add_block("data_deletealloflist", fields={"LIST": [list_name, lid]})

    def add_to_list(self, list_name, val):
        lid = self._ensure_list(list_name)
        bid = self._add_block("data_addtolist", fields={"LIST": [list_name, lid]})
        self.blocks[bid]["inputs"]["ITEM"] = self._emit_input(val, bid)
        return bid

    def replace_item(self, list_name, idx, val):
        lid = self._ensure_list(list_name)
        bid = self._add_block("data_replaceitemoflist", fields={"LIST": [list_name, lid]})
        self.blocks[bid]["inputs"]["INDEX"] = self._emit_input(idx, bid)
        self.blocks[bid]["inputs"]["ITEM"] = self._emit_input(val, bid)
        return bid

    def reset_timer(self):
        return self._add_block("sensing_resettimer")

    # Motion
    def goto_xy(self, x, y):
        bid = self._add_block("motion_gotoxy")
        self.blocks[bid]["inputs"]["X"] = self._emit_input(x, bid)
        self.blocks[bid]["inputs"]["Y"] = self._emit_input(y, bid)
        return bid

    def set_x(self, x):
        bid = self._add_block("motion_setx")
        self.blocks[bid]["inputs"]["X"] = self._emit_input(x, bid)
        return bid

    def set_y(self, y):
        bid = self._add_block("motion_sety")
        self.blocks[bid]["inputs"]["Y"] = self._emit_input(y, bid)
        return bid

    def change_x(self, dx):
        bid = self._add_block("motion_changexby")
        self.blocks[bid]["inputs"]["DX"] = self._emit_input(dx, bid)
        return bid

    def change_y(self, dy):
        bid = self._add_block("motion_changeyby")
        self.blocks[bid]["inputs"]["DY"] = self._emit_input(dy, bid)
        return bid

    # Looks (for optional Stamp comparison)
    def hide(self):
        return self._add_block("looks_hide")

    def show(self):
        return self._add_block("looks_show")

    def set_size(self, pct):
        bid = self._add_block("looks_setsizeto")
        self.blocks[bid]["inputs"]["SIZE"] = self._emit_input(pct, bid)
        return bid

    def switch_costume(self, name):
        bid = self._add_block("looks_switchcostumeto")
        mid = self._add_block("looks_costume", fields={"COSTUME": [name, None]}, shadow=True)
        self.blocks[mid]["parent"] = bid
        self.blocks[bid]["inputs"]["COSTUME"] = [1, mid]
        return bid

    def set_effect(self, effect_name, val):
        # COLOR, BRIGHTNESS, GHOST
        bid = self._add_block("looks_seteffectto", fields={"EFFECT": [effect_name, None]})
        self.blocks[bid]["inputs"]["VALUE"] = self._emit_input(val, bid)
        return bid

    # Pen
    def pen_clear(self):
        return self._add_block("pen_clear")

    def pen_down(self):
        return self._add_block("pen_penDown")

    def pen_up(self):
        return self._add_block("pen_penUp")

    def pen_stamp(self):
        return self._add_block("pen_stamp")

    def pen_set_size(self, size):
        bid = self._add_block("pen_setPenSizeTo")
        self.blocks[bid]["inputs"]["SIZE"] = self._emit_input(size, bid)
        return bid

    def pen_set_color(self, color_expr):
        # Accepts 24-bit RGB or 32-bit ARGB integer!
        bid = self._add_block("pen_setPenColorToColor")
        self.blocks[bid]["inputs"]["COLOR"] = self._emit_input(color_expr, bid, is_color=True)
        return bid

    def pen_set_param(self, param, val):
        # param: 'color', 'saturation', 'brightness', 'transparency'
        bid = self._add_block("pen_setPenColorParamTo")
        mid = self._add_block("pen_menu_colorParam", fields={"colorParam": [param, None]}, shadow=True)
        self.blocks[mid]["parent"] = bid
        self.blocks[bid]["inputs"]["COLOR_PARAM"] = [1, mid]
        self.blocks[bid]["inputs"]["VALUE"] = self._emit_input(val, bid)
        return bid

    # Control
    def _link_chain(self, stmts, parent_id=None):
        stmts = [s for s in stmts if s is not None]
        if not stmts:
            return None
        for i, bid in enumerate(stmts):
            if i == 0:
                self.blocks[bid]["parent"] = parent_id
            else:
                self.blocks[bid]["parent"] = stmts[i - 1]
                self.blocks[stmts[i - 1]]["next"] = bid
        return stmts[0]

    def repeat(self, times, body):
        bid = self._add_block("control_repeat")
        self.blocks[bid]["inputs"]["TIMES"] = self._emit_input(times, bid)
        first = self._link_chain(body, bid)
        if first:
            self.blocks[bid]["inputs"]["SUBSTACK"] = [2, first]
        return bid

    def repeat_until(self, cond, body):
        bid = self._add_block("control_repeat_until")
        self.blocks[bid]["inputs"]["CONDITION"] = self._emit_input(cond, bid, is_bool=True)
        first = self._link_chain(body, bid)
        if first:
            self.blocks[bid]["inputs"]["SUBSTACK"] = [2, first]
        return bid

    def forever(self, body):
        bid = self._add_block("control_forever")
        first = self._link_chain(body, bid)
        if first:
            self.blocks[bid]["inputs"]["SUBSTACK"] = [2, first]
        return bid

    def if_(self, cond, body):
        bid = self._add_block("control_if")
        self.blocks[bid]["inputs"]["CONDITION"] = self._emit_input(cond, bid, is_bool=True)
        first = self._link_chain(body, bid)
        if first:
            self.blocks[bid]["inputs"]["SUBSTACK"] = [2, first]
        return bid

    def if_else(self, cond, then_body, else_body):
        bid = self._add_block("control_if_else")
        self.blocks[bid]["inputs"]["CONDITION"] = self._emit_input(cond, bid, is_bool=True)
        f1 = self._link_chain(then_body, bid)
        f2 = self._link_chain(else_body, bid)
        if f1:
            self.blocks[bid]["inputs"]["SUBSTACK"] = [2, f1]
        if f2:
            self.blocks[bid]["inputs"]["SUBSTACK2"] = [2, f2]
        return bid

    def stop_this(self):
        return self._add_block(
            "control_stop",
            fields={"STOP_OPTION": ["this script", None]},
            mutation={"tagName": "mutation", "children": [], "hasnext": "false"},
        )

    def stop_all(self):
        return self._add_block(
            "control_stop",
            fields={"STOP_OPTION": ["all", None]},
            mutation={"tagName": "mutation", "children": [], "hasnext": "false"},
        )

    def wait(self, secs):
        bid = self._add_block("control_wait")
        self.blocks[bid]["inputs"]["DURATION"] = self._emit_input(secs, bid)
        return bid

    # Custom Procedures (Run Without Screen Refresh = warp=True!)
    def define_proc(self, name, arg_names=None, warp=True, body=None):
        arg_names = arg_names or []
        arg_ids = [f"arg_{name}_{a}" for a in arg_names]
        proccode = name + (" " + " ".join(["%s"] * len(arg_names)) if arg_names else "")
        def_id = self._add_block("procedures_definition", top_level=True)
        proto_id = self._add_block(
            "procedures_prototype",
            shadow=True,
            mutation={
                "tagName": "mutation",
                "children": [],
                "proccode": proccode,
                "argumentids": json.dumps(arg_ids),
                "argumentnames": json.dumps(arg_names),
                "argumentdefaults": json.dumps([""] * len(arg_names)),
                "warp": "true" if warp else "false",
            },
        )
        self.blocks[proto_id]["parent"] = def_id
        for aname, aid in zip(arg_names, arg_ids):
            rep_id = self._add_block(
                "argument_reporter_string_number",
                fields={"VALUE": [aname, None]},
                shadow=True,
            )
            self.blocks[rep_id]["parent"] = proto_id
            self.blocks[proto_id]["inputs"][aid] = [1, rep_id]
        self.blocks[def_id]["inputs"]["custom_block"] = [1, proto_id]

        if body:
            first = self._link_chain(body, def_id)
            if first:
                self.blocks[def_id]["next"] = first

        return (proccode, arg_ids, warp)

    def call_proc(self, proc_handle, *args):
        proccode, arg_ids, warp = proc_handle
        assert len(args) == len(arg_ids), f"Expected {len(arg_ids)} args for {proccode}, got {len(args)}"
        bid = self._add_block(
            "procedures_call",
            mutation={
                "tagName": "mutation",
                "children": [],
                "proccode": proccode,
                "argumentids": json.dumps(arg_ids),
                "warp": "true" if warp else "false",
            },
        )
        for aid, val in zip(arg_ids, args):
            self.blocks[bid]["inputs"][aid] = self._emit_input(val, bid)
        return bid

    def when_flag_clicked(self, body):
        hat = self._add_block("event_whenflagclicked", top_level=True)
        first = self._link_chain(body, hat)
        if first:
            self.blocks[hat]["next"] = first
        return hat

    def to_target_dict(self):
        return {
            "isStage": self.is_stage,
            "name": self.name,
            "variables": {vid: [vname, init] for vname, (vid, init) in self.variables.items()},
            "lists": {lid: [lname, init] for lname, (lid, init) in self.lists.items()},
            "broadcasts": {},
            "blocks": self.blocks,
            "comments": {},
            "currentCostume": 0,
            "costumes": self.costumes,
            "sounds": [],
            "volume": 100,
            "layerOrder": 0 if self.is_stage else 1,
            **(
                {
                    "tempo": 60,
                    "videoTransparency": 50,
                    "videoState": "on",
                    "textToSpeechLanguage": None,
                }
                if self.is_stage
                else {
                    "visible": False,
                    "x": 0,
                    "y": 0,
                    "size": 100,
                    "direction": 90,
                    "draggable": False,
                    "rotationStyle": "all around",
                }
            ),
        }


class ProjectBuilder:
    def __init__(self):
        self.stage = SpriteBuilder("Stage", is_stage=True)
        self.sprites = []

    def add_sprite(self, name="Renderer"):
        s = SpriteBuilder(name, is_stage=False)
        self.sprites.append(s)
        return s

    def save_sb3(self, out_path):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        targets = [self.stage.to_target_dict()] + [s.to_target_dict() for s in self.sprites]
        proj = {
            "targets": targets,
            "monitors": [],
            "extensions": ["pen"],
            "meta": {"semver": "3.0.0", "vm": "0.2.0", "agent": "scratch-ue5-pen-compiler"},
        }
        assets = {}
        for t in [self.stage] + self.sprites:
            assets.update(t._extra_assets)

        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(proj, separators=(",", ":")))
            for fname, content in assets.items():
                zf.writestr(fname, content)
        return out_path
