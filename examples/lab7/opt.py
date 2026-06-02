#!/usr/bin/env python3
"""
Локальные оптимизации if-else в урощённом TAC.
Оптимизации:
  1. Constant Folding — если операнды условия — константы, вычислить условие
     и заменить условный переход на безусловный.
  2. Predication — если обе ветки if-else присваивают одной и той же переменной
     и сразу переходят в общий блок, заменить на select.
"""

def constant_folding(ir):
    """
    ir: список строк. Возвращает новый список строк.
    Обрабатывает случай, когда условие t = const1 > const2.
    Заменяет if t goto L1 else goto L2 на goto L_target.
    """
    result = []
    i = 0
    while i < len(ir):
        line = ir[i].strip()
        # Поиск шаблона: if tVar goto L1 else goto L2
        if line.startswith('if ') and 'goto' in line and 'else goto' in line:
            parts = line.split()
            if len(parts) == 7 and parts[0] == 'if' and parts[2] == 'goto' and parts[4] == 'else' and parts[5] == 'goto':
                cond_var = parts[1]
                label_then = parts[3]
                label_else = parts[6]

                # Ищем определение cond_var: tVar = left > right
                cond_def = None
                for prev in result + ir[i:]:
                    if prev.startswith(cond_var + ' = '):
                        cond_def = prev.strip()
                        break
                if cond_def:
                    # Извлекаем левый и правый операнд из 't = left > right'
                    try:
                        expr = cond_def.split('=', 1)[1].strip()
                        # Поддерживаем только оператор '>'
                        if '>' in expr:
                            left, right = expr.split('>', 1)
                            left_val = int(left.strip())
                            right_val = int(right.strip())
                            const_cond = left_val > right_val
                            target = label_then if const_cond else label_else
                            result.append(f'goto {target}   ; folded constant (const condition)')
                            i += 1
                            continue
                    except ValueError:
                        # Не константы — оставляем как есть
                        pass
        result.append(line)
        i += 1
    return result


def predication(ir):
    """
    ir: список строк. Возвращает новый список строк.
    Ищет шаблон:
        if cond goto L1 else goto L2
        L1:
            var = val1
            goto L_common
        L2:
            var = val2
            goto L_common
    и заменяет на:
        var = select cond, val1, val2
        L_common: ...
    """
    result = []
    i = 0
    n = len(ir)
    while i < n:
        line = ir[i].strip()
        if line.startswith('if ') and 'goto' in line and 'else goto' in line:
            parts = line.split()
            if len(parts) == 7 and parts[0] == 'if' and parts[2] == 'goto' and parts[4] == 'else' and parts[5] == 'goto':
                cond = parts[1]
                label_then = parts[3]
                label_else = parts[6]

                # Пытаемся сопоставить шаблон then-ветки
                if i+4 < n:
                    line_then_label = ir[i+1].strip()
                    line_then_assign = ir[i+2].strip() if i+2 < n else ''
                    line_then_goto = ir[i+3].strip() if i+3 < n else ''

                    if (line_then_label == label_then + ':' and
                        '=' in line_then_assign and
                        line_then_goto.startswith('goto ')):
                        # Извлекаем var и val1
                        var1, val1 = line_then_assign.split('=', 1)
                        var1 = var1.strip()
                        val1 = val1.strip()
                        goto_target_then = line_then_goto.split('goto ')[1].strip()

                        # Теперь проверяем else-ветку, начиная со следующей строки после then_goto
                        j = i+4
                        if j+2 < n:
                            line_else_label = ir[j].strip()
                            line_else_assign = ir[j+1].strip()
                            line_else_goto = ir[j+2].strip() if j+2 < n else ''

                            if (line_else_label == label_else + ':' and
                                '=' in line_else_assign and
                                line_else_goto.startswith('goto ')):
                                var2, val2 = line_else_assign.split('=', 1)
                                var2 = var2.strip()
                                val2 = val2.strip()
                                goto_target_else = line_else_goto.split('goto ')[1].strip()

                                # Проверяем, что переменная одна и та же и целевая метка одна
                                if var1 == var2 and goto_target_then == goto_target_else:
                                    # Можно заменить
                                    result.append(f'{var1} = select {cond}, {val1}, {val2}')
                                    # Пропускаем обработанные строки: if, then_label, then_assign, then_goto, else_label, else_assign, else_goto
                                    i = j+3  # станет на следующую строку после else_goto
                                    continue
        result.append(line)
        i += 1
    return result


def print_ir(title, ir):
    print(f'=== {title} ===')
    for idx, line in enumerate(ir):
        print(f'{idx:2d}: {line}')
    print()


if __name__ == '__main__':
    # Пример 1: с переменными (без констант)
    ir1 = [
        't1 = a > b',
        'if t1 goto L1 else goto L2',
        'L1:',
        '    retval = a',
        '    goto L3',
        'L2:',
        '    retval = b',
        '    goto L3',
        'L3:',
        '    return retval'
    ]

    print_ir('Входной IR (переменные)', ir1)

    # Применяем constant_folding (ничего не изменит, т.к. a и b не константы)
    after_cf1 = constant_folding(ir1)
    print_ir('После Constant Folding (не применилась)', after_cf1)

    # Применяем predication
    after_pred1 = predication(ir1)
    print_ir('После Predication (замена на select)', after_pred1)

    # Пример 2: с явными константами в условии
    ir2 = [
        't1 = 5 > 3',
        'if t1 goto L1 else goto L2',
        'L1:',
        '    retval = a',
        '    goto L3',
        'L2:',
        '    retval = b',
        '    goto L3',
        'L3:',
        '    return retval'
    ]

    print_ir('Входной IR (константы в условии)', ir2)
    after_cf2 = constant_folding(ir2)
    print_ir('После Constant Folding', after_cf2)

    # Для полной демонстрации можно применить predication после CF, но в данном примере
    # структура не соответствует predication, т.к. после свёртки остался goto L1, но метки не убраны.
    # В реальном коде нужен также dead code elimination, но для задания достаточно показать,
    # что условный переход свёрнут. Оставим как есть.