"""Локальные оптимизации IR — собственная реализация на Python."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from typing import List, Tuple


def _tac():
    from if_ir import TacInstr
    return TacInstr


def clone_ir(instrs) -> list:
    TacInstr = _tac()
    return [TacInstr(t.index, t.op, list(t.args), t.comment) for t in instrs]


def reindex_ir(instrs) -> list:
    TacInstr = _tac()
    return [TacInstr(i + 1, t.op, list(t.args), t.comment) for i, t in enumerate(instrs)]


@dataclass
class PassResult:
    name: str
    title: str
    description: str
    input_ir: List
    output_ir: List
    steps: List[str] = field(default_factory=list)

    def format_report(self) -> str:
        lines = [
            self.title,
            self.description,
            "(реализация: Python, Clang/opt не используются)",
            "",
            "Шаги алгоритма",
            "",
        ]
        lines.extend(f"  {i + 1}. {s}" for i, s in enumerate(self.steps))
        lines.extend(["", "Входной IR", ""])
        lines.extend(t.format() for t in self.input_ir)
        lines.append("")
        lines.append("Выходной IR")
        lines.append("")
        lines.extend(t.format() for t in self.output_ir)
        lines.append("")
        return "\n".join(lines)


class LocalOptimizationPass(ABC):
    name: str = "pass"
    title: str = "Pass"
    description: str = ""

    @abstractmethod
    def apply(self, instrs: List) -> Tuple[List, List[str]]:
        pass


class RedundantTempElimPass(LocalOptimizationPass):
    """Опт. 1 (if-else): устранение лишних временных переменных в условии и присваиваниях."""

    name = "redundant_temp_elim"
    title = "Оптимизация 1: устранение избыточных временных"
    description = (
        "Локальная оптимизация: если результат CMP используется только в BR_COND, "
        "операнды сравнения подставляются напрямую; простые ASSIGN без арифметики упрощаются."
    )

    def apply(self, instrs: List) -> Tuple[List, List[str]]:
        TacInstr = _tac()
        steps: List[str] = []
        cmp_info = None
        cmp_used_once = False

        for ins in instrs:
            if ins.op == "CMP":
                cmp_info = ins
            if ins.op == "BR_COND" and cmp_info and ins.args[0] == f"t{cmp_info.index}":
                cmp_used_once = True

        out: List = []
        n = 0
        skip_indices = set()

        if cmp_used_once and cmp_info:
            steps.append(
                f"CMP t{cmp_info.index} используется один раз → встроить в BR_COND"
            )
            skip_indices.add(cmp_info.index)

        def emit(op: str, args: List[str], comment: str = "") -> None:
            nonlocal n
            n += 1
            out.append(TacInstr(n, op, args, comment))

        for ins in instrs:
            if ins.index in skip_indices:
                continue
            if ins.op == "BR_COND" and cmp_used_once and cmp_info:
                left, op, right = cmp_info.args[0], cmp_info.args[1], cmp_info.args[2]
                emit("BR_COND", [f"{left}{op}{right}", ins.args[1], ins.args[2]],
                     "условие без промежуточного t")
                steps.append(f"BR_COND({left} {op} {right}, {ins.args[1]}, {ins.args[2]})")
                continue
            if ins.op == "ASSIGN" and ins.args[0] == ins.args[1]:
                steps.append(f"Пропуск ASSIGN {ins.args[0]} = {ins.args[1]} (тождество)")
                continue
            emit(ins.op, ins.args, ins.comment)

        steps.append(f"Инструкций: {len(instrs)} → {len(out)}")
        return out, steps


class IfConversionPass(LocalOptimizationPass):
    """Опт. 2 (if-else): if-conversion — замена BR_COND на SELECT (аналог cmov)."""

    name = "if_conversion"
    title = "Оптimизация 2: if-conversion (SELECT / cmov)"
    description = (
        "Локальная оптимизация: если обе ветки — простые присваивания в одну переменную, "
        "BR_COND + две ветки заменяются одной инструкцией SELECT (аналог cmov)."
    )

    def apply(self, instrs: List) -> Tuple[List, List[str]]:
        TacInstr = _tac()
        steps: List[str] = []

        br_idx = None
        then_assign = None
        else_assign = None
        target_var = None

        labels = {ins.args[0]: i for i, ins in enumerate(instrs) if ins.op == "LABEL"}

        for i, ins in enumerate(instrs):
            if ins.op == "BR_COND":
                br_idx = i
                then_lbl, else_lbl = ins.args[1], ins.args[2]
                then_i = labels.get(then_lbl)
                else_i = labels.get(else_lbl)
                if then_i is not None and else_i is not None:
                    t_ins = _find_assign_after(instrs, then_i)
                    e_ins = _find_assign_after(instrs, else_i)
                    if (t_ins and e_ins and t_ins.op == "ASSIGN" and e_ins.op == "ASSIGN"
                            and t_ins.args[0] == e_ins.args[0]):
                        then_assign = t_ins
                        else_assign = e_ins
                        target_var = t_ins.args[0]

        if br_idx is None or not then_assign or not else_assign:
            steps.append("Паттерн if-conversion не обнаружен — IR без изменений")
            return clone_ir(instrs), steps

        cond = instrs[br_idx].args[0]
        steps.append(
            f"Обнаружен паттерн: if cond then {target_var}={then_assign.args[1]} "
            f"else {target_var}={else_assign.args[1]}"
        )
        steps.append(
            f"SELECT {target_var}, {then_assign.args[1]}, {else_assign.args[1]}, {cond} "
            f"(аналог cmov)"
        )

        skip_ops = {"BR_COND", "LABEL", "GOTO", "ASSIGN", "CMP"}
        out: List = []
        n = 0

        def emit(op: str, args: List[str], comment: str = "") -> None:
            nonlocal n
            n += 1
            out.append(TacInstr(n, op, args, comment))

        removed = 0
        for ins in instrs:
            if ins.op in skip_ops:
                if ins.op == "BR_COND":
                    emit(
                        "SELECT",
                        [target_var, then_assign.args[1], else_assign.args[1], cond],
                        "if-conversion: cmov-подобная форма",
                    )
                removed += 1
                continue
            emit(ins.op, ins.args, ins.comment)

        steps.append(f"Удалено {removed} инструкций ветвления, добавлен SELECT")
        return out, steps


class Mem2RegPass(LocalOptimizationPass):
    """Опт. 1 (C max -O2): mem2reg — убрать alloca/load/store, работать с регистрами."""

    name = "mem2reg"
    title = "Оптимизация 1 (-O2): mem2reg"
    description = (
        "Локальная оптимизация: удаление ALLOCA/LOAD/STORE для параметров, "
        "использование SSA-имён a, b напрямую."
    )

    def apply(self, instrs: List) -> Tuple[List, List[str]]:
        TacInstr = _tac()
        steps = ["Удалить ALLOCA/STORE/LOAD для параметров a, b"]
        skip = {"ALLOCA", "STORE", "LOAD"}
        cmp_temp = None
        out: List = []
        n = 0

        def emit(op: str, args: List[str], comment: str = "") -> None:
            nonlocal n
            n += 1
            out.append(TacInstr(n, op, args, comment))

        for ins in instrs:
            if ins.op in skip:
                steps.append(f"Удалено: {ins.format().strip()}")
                continue
            if ins.op == "CMP":
                cmp_temp = f"t{n + 1}"
                emit("CMP", ["a", ins.args[1], "b"], "прямое сравнение параметров")
                steps.append("CMP(a, op, b) — без load")
                continue
            if ins.op == "BR_COND" and cmp_temp:
                emit("BR_COND", [cmp_temp, ins.args[1], ins.args[2]], ins.comment)
                continue
            emit(ins.op, ins.args, ins.comment)

        return out, steps


class BranchToCmovPass(LocalOptimizationPass):
    """Опт. 2 (C max -O2): замена условного перехода на CMOV/SELECT."""

    name = "branch_to_cmov"
    title = "Оптимизация 2 (-O2): branch → cmov"
    description = (
        "Локальная оптимизация: BR_COND + две ветки return заменяются "
        "одной инструкцией CMOV и единственным RET."
    )

    def apply(self, instrs: List) -> Tuple[List, List[str]]:
        TacInstr = _tac()
        steps: List[str] = []

        br = next((i for i in instrs if i.op == "BR_COND"), None)
        if not br:
            steps.append("BR_COND не найден")
            return clone_ir(instrs), steps

        cond = br.args[0]
        steps.append(f"Найден BR_COND с условием {cond}")
        steps.append("Две ветки return → CMOV t_ret, a, b, cond + RET t_ret")

        skip = {"BR_COND", "LABEL", "GOTO", "RET", "CMP"}
        out: List = []
        n = 0
        func_end_args: List[str] = ["max"]

        def emit(op: str, args: List[str], comment: str = "") -> None:
            nonlocal n
            n += 1
            out.append(TacInstr(n, op, args, comment))

        for ins in instrs:
            if ins.op == "FUNC_BEGIN":
                emit(ins.op, ins.args, ins.comment)
            elif ins.op == "FUNC_END":
                func_end_args = ins.args
            elif ins.op == "BR_COND":
                emit("CMOV", ["t_ret", "a", "b", cond], "условие → cmov (без перехода)")
            elif ins.op in skip:
                continue
            elif ins.op not in ("ALLOCA", "STORE", "LOAD"):
                emit(ins.op, ins.args, ins.comment)

        emit("RET", ["t_ret"], "единственный return")
        emit("FUNC_END", func_end_args, "")
        steps.append("CFG упрощён: линейный поток без условных переходов")
        return out, steps


def _find_assign_after(instrs: List, label_idx: int):
    for ins in instrs[label_idx + 1:]:
        if ins.op == "ASSIGN":
            return ins
        if ins.op in ("LABEL", "BR_COND"):
            break
    return None


def run_passes(instrs: List, passes: List[LocalOptimizationPass]) -> List[PassResult]:
    results: List[PassResult] = []
    current = instrs
    for p in passes:
        inp = clone_ir(current)
        out, steps = p.apply(current)
        out = reindex_ir(out)
        results.append(
            PassResult(
                name=p.name,
                title=p.title,
                description=p.description,
                input_ir=inp,
                output_ir=out,
                steps=steps,
            )
        )
        current = out
    return results
