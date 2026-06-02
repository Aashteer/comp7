"""Построение CFG из TAC (собственный алгоритм)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class CFGEdge:
    src: str
    dst: str
    label: str = ""
    prob: Optional[float] = None


@dataclass
class CFGBlock:
    name: str
    instr_indices: List[int] = field(default_factory=list)
    preds: Set[str] = field(default_factory=set)
    succs: Set[str] = field(default_factory=set)


@dataclass
class CFG:
    blocks: Dict[str, CFGBlock] = field(default_factory=dict)
    edges: List[CFGEdge] = field(default_factory=list)
    entry: str = "entry"

    def format_text(self, instrs=None, branch_prob: bool = False) -> str:
        lines = ["CFG (собственный алгоритм построения):", ""]
        if branch_prob:
            lines.append("Режим: -branch-prob (вероятности на рёбрах, структура та же)")
            lines.append("")

        for name in self._order():
            b = self.blocks[name]
            lines.append(f"Блок [{name}]:")
            if instrs:
                for idx in b.instr_indices:
                    if 0 <= idx - 1 < len(instrs):
                        lines.append(f"  {instrs[idx - 1].format()}")
            if b.preds:
                lines.append(f"  preds: {sorted(b.preds)}")
            if b.succs:
                lines.append(f"  succs: {sorted(b.succs)}")
            lines.append("")

        lines.append("Рёбра:")
        for e in self.edges:
            prob_s = f", prob={e.prob:.2f}" if e.prob is not None else ""
            lbl = f" [{e.label}]" if e.label else ""
            lines.append(f"  {e.src} → {e.dst}{lbl}{prob_s}")

        lines.append("")
        lines.append(self._ascii_graph())
        return "\n".join(lines)

    def _order(self) -> List[str]:
        seen: List[str] = []
        if self.entry in self.blocks:
            seen.append(self.entry)
        for name in sorted(self.blocks):
            if name not in seen:
                seen.append(name)
        return seen

    def _ascii_graph(self) -> str:
        lines = ["ASCII-граф:"]
        for e in self.edges:
            prob = f" ({e.prob:.0%})" if e.prob is not None else ""
            lbl = f" [{e.label}]" if e.label else ""
            lines.append(f"  ({e.src}) --{lbl}{prob}--> ({e.dst})")
        return "\n".join(lines)


def build_cfg(instrs, func_name: str = "max") -> CFG:
    """Построить CFG из списка TacInstr."""
    cfg = CFG()
    label_to_block: Dict[str, str] = {}
    block_starts: Dict[int, str] = {}
    leaders: Set[int] = {1}

    for i, ins in enumerate(instrs, start=1):
        if ins.op == "LABEL":
            leaders.add(i)
            label_to_block[ins.args[0]] = ins.args[0]
            block_starts[i] = ins.args[0]
        if ins.op in ("BR_COND", "GOTO"):
            if i + 1 <= len(instrs):
                leaders.add(i + 1)
            if ins.op == "BR_COND":
                for lbl in ins.args[1:]:
                    for j, other in enumerate(instrs, start=1):
                        if other.op == "LABEL" and other.args[0] == lbl:
                            leaders.add(j)
            elif ins.op == "GOTO":
                lbl = ins.args[0]
                for j, other in enumerate(instrs, start=1):
                    if other.op == "LABEL" and other.args[0] == lbl:
                        leaders.add(j)

    if not block_starts:
        block_starts[1] = "entry"
        leaders.add(1)

    sorted_leaders = sorted(leaders)
    block_names: List[str] = []
    for idx, start in enumerate(sorted_leaders):
        if start in block_starts:
            name = block_starts[start]
        else:
            name = "entry" if idx == 0 else f"B{idx}"
        block_names.append(name)
        cfg.blocks[name] = CFGBlock(name=name)

    cfg.entry = block_names[0] if block_names else "entry"

    for bi, start in enumerate(sorted_leaders):
        bname = block_names[bi]
        end = sorted_leaders[bi + 1] if bi + 1 < len(sorted_leaders) else len(instrs) + 1
        block = cfg.blocks[bname]
        for idx in range(start, end):
            if idx <= len(instrs):
                block.instr_indices.append(idx)

    for bi, start in enumerate(sorted_leaders):
        bname = block_names[bi]
        last_idx = block.instr_indices[-1] if block.instr_indices else start
        if last_idx > len(instrs):
            continue
        last = instrs[last_idx - 1]

        if last.op == "BR_COND":
            then_b = _resolve_label(last.args[1], label_to_block, cfg)
            else_b = _resolve_label(last.args[2], label_to_block, cfg)
            _add_edge(cfg, bname, then_b, "true")
            _add_edge(cfg, bname, else_b, "false")
        elif last.op == "GOTO":
            tgt = _resolve_label(last.args[0], label_to_block, cfg)
            _add_edge(cfg, bname, tgt, "")
        elif last.op == "RET":
            pass
        elif bi + 1 < len(block_names):
            _add_edge(cfg, bname, block_names[bi + 1], "fallthrough")

    return cfg


def _resolve_label(lbl: str, mapping: Dict[str, str], cfg: CFG) -> str:
    if lbl in mapping:
        name = mapping[lbl]
    else:
        name = lbl
    if name not in cfg.blocks:
        cfg.blocks[name] = CFGBlock(name=name)
    return name


def _add_edge(cfg: CFG, src: str, dst: str, label: str) -> None:
    cfg.edges.append(CFGEdge(src, dst, label))
    if src in cfg.blocks:
        cfg.blocks[src].succs.add(dst)
    if dst in cfg.blocks:
        cfg.blocks[dst].preds.add(src)


def apply_branch_prob(cfg: CFG, then_prob: float = 0.5) -> CFG:
    """Добавить вероятности на рёбра BR_COND (аналог -branch-prob)."""
    import copy

    new_cfg = copy.deepcopy(cfg)
    else_prob = 1.0 - then_prob
    for e in new_cfg.edges:
        if e.label == "true":
            e.prob = then_prob
        elif e.label == "false":
            e.prob = else_prob
    return new_cfg


def cfg_structure_equal(a: CFG, b: CFG) -> bool:
    """Сравнить топологию CFG (без вероятностей)."""
    edges_a = {(e.src, e.dst, e.label) for e in a.edges}
    edges_b = {(e.src, e.dst, e.label) for e in b.edges}
    return edges_a == edges_b and set(a.blocks) == set(b.blocks)
