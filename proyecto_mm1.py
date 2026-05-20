# ==============================================================================
# PSWE-14 Ingeniería de Rendimiento de Sistemas
# PROYECTO #1 — Análisis de Rendimiento M/M/1 de la Computadora
#
# Integrantes del grupo:
#   - Manuel de Jesús Sanabria Montoya
#   - Randall Sánchez Rivera
#   - Duván Andrey Vázquez López
#
# Descripción:
#   Programa que obtiene métricas reales del sistema operativo (λ y μ),
#   aplica las fórmulas del modelo de colas M/M/1 y genera un reporte PDF
#   con todos los resultados y su interpretación.
# ==============================================================================

import sys
import psutil
import time
import datetime
import platform
import socket
import os

# Forzar UTF-8 en la salida estándar (necesario en terminales Windows cp1252)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, HRFlowable
)

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ──────────────────────────────────────────────────────────────────────────────

GROUP_MEMBERS = [
    "Manuel de Jesús Sanabria Montoya",
    "Randall Sánchez Rivera",
    "Duván Andrey Vázquez López",
]

SAMPLING_SECONDS = 10   # Duración del intervalo de muestreo del SO

OUTPUT_PDF = "resultado_mm1.pdf"

# Colores para el PDF
C_AZUL_OSCURO = colors.HexColor('#1a3a6b')
C_AZUL_MEDIO  = colors.HexColor('#2563b0')
C_AZUL_CLARO  = colors.HexColor('#dbeafe')
C_GRIS        = colors.HexColor('#f3f4f6')
C_VERDE       = colors.HexColor('#166534')
C_ROJO        = colors.HexColor('#991b1b')
C_BLANCO      = colors.white


# ──────────────────────────────────────────────────────────────────────────────
# 1. OBTENER INFORMACIÓN DEL SISTEMA
# ──────────────────────────────────────────────────────────────────────────────

def get_system_info():
    """Recopila información general de hardware y SO."""
    mem  = psutil.virtual_memory()
    freq = psutil.cpu_freq()
    return {
        'hostname'          : socket.gethostname(),
        'os'                : f"{platform.system()} {platform.release()} ({platform.version()})",
        'processor'         : platform.processor(),
        'cpu_cores_physical': psutil.cpu_count(logical=False),
        'cpu_cores_logical' : psutil.cpu_count(logical=True),
        'cpu_freq_mhz'      : freq.current if freq else 0,
        'ram_total_gb'      : mem.total / (1024 ** 3),
        'ram_used_gb'       : mem.used  / (1024 ** 3),
        'ram_percent'       : mem.percent,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 2. MEDIR λ Y μ DESDE EL SISTEMA OPERATIVO
# ──────────────────────────────────────────────────────────────────────────────

def measure_lambda_mu(interval=SAMPLING_SECONDS):
    """
    Obtiene λ y μ directamente del sistema operativo usando psutil.

    λ (tasa de llegada):
        Se obtiene del contador de interrupciones del CPU expuesto por el SO.
        Las interrupciones (hardware y software) representan las solicitudes que
        llegan al procesador por unidad de tiempo.
        Fórmula: λ = Δinterrupciones / Δtiempo

    μ (tasa de servicio):
        Se deriva de la relación fundamental ρ = λ/μ.
        El SO expone directamente la utilización ρ (cpu_percent).
        Despejando: μ = λ / ρ
        Representa la capacidad máxima del CPU en interrupciones por segundo.
    """
    print(f"\n  Recolectando métricas del SO durante {interval} segundos...")

    # Lectura inicial de contadores del SO
    stats_before = psutil.cpu_stats()

    # cpu_percent mide la utilización real durante el intervalo (bloqueante)
    cpu_percent = psutil.cpu_percent(interval=interval)

    # Lectura final de contadores del SO
    stats_after = psutil.cpu_stats()

    # ── λ: interrupciones por segundo ──────────────────────────────────────
    total_interrupts   = stats_after.interrupts   - stats_before.interrupts
    total_ctx_switches = stats_after.ctx_switches - stats_before.ctx_switches

    lambda_rate        = total_interrupts   / interval
    ctx_switches_per_s = total_ctx_switches / interval

    # ── ρ: utilización del CPU (0.0 – 1.0) ─────────────────────────────────
    rho_measured = cpu_percent / 100.0
    rho_measured = max(0.001, min(rho_measured, 0.999))   # evitar extremos

    # ── μ: capacidad de servicio ─────────────────────────────────────────────
    if lambda_rate > 0:
        mu_rate = lambda_rate / rho_measured
    else:
        # Sin interrupciones: usar frecuencia del CPU como estimado base
        freq = psutil.cpu_freq()
        mu_rate    = (freq.current * 1_000) if freq else 1_000_000
        lambda_rate = rho_measured * mu_rate

    return {
        'lambda'            : lambda_rate,
        'mu'                : mu_rate,
        'rho_measured'      : rho_measured,
        'cpu_percent'       : cpu_percent,
        'interrupts_total'  : total_interrupts,
        'ctx_switches_per_s': ctx_switches_per_s,
        'interval'          : interval,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 3. CALCULAR MÉTRICAS DEL MODELO M/M/1
# ──────────────────────────────────────────────────────────────────────────────

def calculate_mm1(lambda_rate, mu_rate):
    """
    Aplica las fórmulas cerradas del modelo M/M/1.

    Supuestos del modelo:
      - Proceso de llegadas: Poisson con tasa λ
      - Tiempo de servicio: Exponencial con tasa μ
      - Número de servidores: 1 (el CPU)
      - Capacidad de la cola: Infinita
      - Disciplina: FCFS (First Come, First Served)

    Condición de estabilidad: ρ = λ/μ < 1

    Fórmulas:
      ρ  = λ / μ
      L  = ρ / (1 − ρ)           número promedio en el sistema
      Lq = ρ² / (1 − ρ)          número promedio en cola
      W  = 1 / (μ − λ)           tiempo promedio en el sistema  [segundos]
      Wq = λ / [μ(μ − λ)]        tiempo promedio en cola        [segundos]
    """
    rho    = lambda_rate / mu_rate
    stable = rho < 1.0

    rho_c  = min(rho, 0.999)    # valor de cálculo (evita división por cero)

    L  = rho_c / (1 - rho_c)
    Lq = (rho_c ** 2) / (1 - rho_c)

    if stable and (mu_rate - lambda_rate) > 0:
        W  = 1 / (mu_rate - lambda_rate)
        Wq = lambda_rate / (mu_rate * (mu_rate - lambda_rate))
    else:
        W  = float('inf')
        Wq = float('inf')

    return {
        'rho'   : rho,
        'L'     : L,
        'Lq'    : Lq,
        'W'     : W,
        'Wq'    : Wq,
        'stable': stable,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 4. GENERAR PDF CON REPORTLAB
# ──────────────────────────────────────────────────────────────────────────────

def _build_styles():
    base = getSampleStyleSheet()
    return {
        'Title': ParagraphStyle(
            'PTitle', parent=base['Normal'],
            fontSize=20, fontName='Helvetica-Bold',
            textColor=C_AZUL_OSCURO, alignment=TA_CENTER, spaceAfter=3),
        'SubTitle': ParagraphStyle(
            'PSubTitle', parent=base['Normal'],
            fontSize=12, fontName='Helvetica-Bold',
            textColor=C_AZUL_MEDIO, alignment=TA_CENTER, spaceAfter=2),
        'SectionHdr': ParagraphStyle(
            'PSectionHdr', parent=base['Normal'],
            fontSize=10, fontName='Helvetica-Bold',
            textColor=C_BLANCO, leftIndent=6),
        'Body': ParagraphStyle(
            'PBody', parent=base['Normal'],
            fontSize=8.5, leading=13,
            textColor=colors.black, alignment=TA_JUSTIFY, spaceAfter=4),
        'Formula': ParagraphStyle(
            'PFormula', parent=base['Normal'],
            fontSize=8.5, fontName='Courier-Bold',
            textColor=C_AZUL_OSCURO, leftIndent=22, spaceAfter=2),
        'Small': ParagraphStyle(
            'PSmall', parent=base['Normal'],
            fontSize=7, textColor=colors.HexColor('#6b7280'),
            alignment=TA_CENTER),
    }


def _section_bar(text, styles, width=6.5*inch):
    """Barra de encabezado de sección con fondo azul."""
    t = Table([[Paragraph(text, styles['SectionHdr'])]], colWidths=[width])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_AZUL_MEDIO),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
    ]))
    return t


def _fmt(val, unit='', prec=4):
    """Formatea un valor numérico o infinito para mostrarlo en tabla."""
    if val == float('inf'):
        return '∞  (sistema saturado)'
    return f"{val:.{prec}f} {unit}".strip()


def _table(data, col_widths, header_rows=1):
    """Crea una tabla estilizada estándar."""
    t = Table(data, colWidths=col_widths)
    style = [
        ('BACKGROUND',    (0, 0), (-1, header_rows - 1), C_AZUL_OSCURO),
        ('TEXTCOLOR',     (0, 0), (-1, header_rows - 1), C_BLANCO),
        ('FONTNAME',      (0, 0), (-1, header_rows - 1), 'Helvetica-Bold'),
        ('FONTSIZE',       (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, header_rows), (-1, -1), [C_BLANCO, C_GRIS]),
        ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#d1d5db')),
        ('TOPPADDING',     (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 4),
        ('LEFTPADDING',    (0, 0), (-1, -1), 6),
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
    ]
    t.setStyle(TableStyle(style))
    return t


def generate_pdf(sys_info, metrics, mm1, output_path=OUTPUT_PDF):
    """Construye el documento PDF con todos los resultados."""

    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        rightMargin=0.75*inch, leftMargin=0.75*inch,
        topMargin=0.75*inch,   bottomMargin=0.75*inch,
    )
    S  = _build_styles()
    CW = 6.5 * inch     # ancho total de contenido
    now = datetime.datetime.now()
    story = []

    # ── ENCABEZADO ────────────────────────────────────────────────────────────
    story += [
        Paragraph("PSWE-14 — Ingeniería de Rendimiento de Sistemas", S['SubTitle']),
        Paragraph("Proyecto #1 — Análisis de Rendimiento M/M/1", S['Title']),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=2, color=C_AZUL_OSCURO),
        Spacer(1, 6),
    ]

    # Tabla de metadatos (fecha, integrantes, universidad)
    meta = _table([
        ['Fecha de análisis:', now.strftime('%d/%m/%Y   %H:%M:%S'),
         'Universidad:', 'Cenfotec'],
        ['Integrantes del grupo:', '\n'.join(GROUP_MEMBERS),
         'Curso:', 'PSWE-14'],
    ], [1.3*inch, 2.7*inch, 1.0*inch, 1.5*inch], header_rows=0)
    meta.setStyle(TableStyle([
        ('FONTNAME',  (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME',  (2, 0), (2, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), C_AZUL_OSCURO),
        ('TEXTCOLOR', (2, 0), (2, -1), C_AZUL_OSCURO),
        ('FONTSIZE',  (0, 0), (-1, -1), 8),
        ('VALIGN',    (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#d1d5db')),
    ]))
    story += [meta, Spacer(1, 10)]

    # ── SECCIÓN 1: INFORMACIÓN DEL SISTEMA ───────────────────────────────────
    story += [
        _section_bar("1.  Información del Sistema", S),
        Spacer(1, 4),
        _table([
            ['Parámetro', 'Valor'],
            ['Hostname', sys_info['hostname']],
            ['Sistema Operativo', sys_info['os']],
            ['Procesador', sys_info['processor'][:72]],
            ['Núcleos Físicos / Lógicos',
             f"{sys_info['cpu_cores_physical']} / {sys_info['cpu_cores_logical']}"],
            ['Frecuencia CPU', f"{sys_info['cpu_freq_mhz']:.0f} MHz"],
            ['RAM Total', f"{sys_info['ram_total_gb']:.2f} GB"],
            ['RAM en uso',
             f"{sys_info['ram_used_gb']:.2f} GB  ({sys_info['ram_percent']:.1f}%)"],
        ], [2.2*inch, 4.3*inch]),
        Spacer(1, 10),
    ]

    # ── SECCIÓN 2: METODOLOGÍA ────────────────────────────────────────────────
    story += [
        _section_bar("2.  Metodología — Obtención de λ y μ desde el Sistema Operativo", S),
        Spacer(1, 5),
        Paragraph(
            "<b>λ — Tasa de llegada (interrupciones/segundo):</b>  El sistema operativo "
            "mantiene un contador acumulado de interrupciones del CPU, accesible mediante "
            "<i>psutil.cpu_stats().interrupts</i>. Se toman dos lecturas del contador con "
            f"un intervalo de {metrics['interval']} segundos entre ellas; la diferencia "
            "dividida entre el intervalo da la tasa de llegada λ. Las interrupciones "
            "(hardware: timers, E/S, red; software: syscalls) representan las solicitudes "
            "que llegan al procesador y son el insumo natural para el rol de λ en el modelo.",
            S['Body']),
        Spacer(1, 3),
        Paragraph(
            "<b>μ — Tasa de servicio (interrupciones/segundo que el CPU puede manejar):</b>  "
            "El SO expone la utilización real del CPU mediante <i>psutil.cpu_percent()</i>, "
            "que corresponde directamente a ρ en el modelo M/M/1.  Despejando de la "
            "relación fundamental ρ = λ/μ se obtiene <b>μ = λ / ρ</b>.  Este valor "
            "representa la capacidad máxima teórica del procesador expresada en "
            "interrupciones por segundo bajo la carga observada.",
            S['Body']),
        Spacer(1, 10),
    ]

    # ── SECCIÓN 3: MEDICIONES OBTENIDAS DEL SO ────────────────────────────────
    story += [
        _section_bar("3.  Mediciones Obtenidas del Sistema Operativo", S),
        Spacer(1, 4),
        _table([
            ['Variable', 'Símbolo', 'Valor medido', 'Fuente en psutil'],
            ['Tasa de llegada', 'λ (lambda)',
             f"{metrics['lambda']:>14,.2f}  interrupciones/s",
             'cpu_stats().interrupts  Δ'],
            ['Tasa de servicio', 'μ (mu)',
             f"{metrics['mu']:>14,.2f}  interrupciones/s",
             'Derivado: μ = λ / ρ'],
            ['Utilización CPU', 'ρ (rho) medido',
             f"{metrics['cpu_percent']:>10.2f} %",
             'cpu_percent(interval=...)'],
            ['Cambios de contexto', '—',
             f"{metrics['ctx_switches_per_s']:>14,.2f}  cambios/s",
             'cpu_stats().ctx_switches  Δ'],
            ['Interrupciones totales', '—',
             f"{metrics['interrupts_total']:>14,}  interrupciones",
             f"Acumuladas en {metrics['interval']} s"],
        ], [1.8*inch, 1.0*inch, 2.0*inch, 1.7*inch]),
        Spacer(1, 10),
    ]

    # ── SECCIÓN 4: FÓRMULAS M/M/1 ────────────────────────────────────────────
    story += [
        _section_bar("4.  Fórmulas del Modelo M/M/1 Aplicadas", S),
        Spacer(1, 5),
    ]
    formulas = [
        ("ρ  =  λ / μ",
         "Factor de utilización del servidor (adimensional, debe ser < 1)"),
        ("L  =  ρ / (1 − ρ)",
         "Número promedio de solicitudes en el sistema  [unidades]"),
        ("Lq =  ρ² / (1 − ρ)",
         "Número promedio de solicitudes esperando en cola  [unidades]"),
        ("W  =  1 / (μ − λ)",
         "Tiempo promedio que una solicitud pasa en el sistema  [segundos]"),
        ("Wq =  λ / [μ · (μ − λ)]",
         "Tiempo promedio de espera en cola antes de ser atendida  [segundos]"),
    ]
    for sym, desc in formulas:
        story.append(Paragraph(
            f"<font name='Courier-Bold'>{sym}</font>"
            f"<font color='#374151'>   →   {desc}</font>",
            S['Formula']))
    story.append(Spacer(1, 10))

    # ── SECCIÓN 5: RESULTADOS M/M/1 ──────────────────────────────────────────
    rho_pct      = mm1['rho'] * 100
    stable_label = "ESTABLE  (ρ < 1)" if mm1['stable'] else "SATURADO  (ρ ≥ 1)"
    stable_color = C_VERDE if mm1['stable'] else C_ROJO

    res_table = _table([
        ['Variable', 'Símbolo', 'Resultado', 'Unidad', 'Interpretación'],
        ['Utilización del servidor', 'ρ',
         f"{rho_pct:.4f}", '%', stable_label],
        ['Solicitudes en sistema', 'L',
         _fmt(mm1['L'], prec=6), 'unidades',
         'Promedio total (cola + en servicio)'],
        ['Solicitudes en cola', 'Lq',
         _fmt(mm1['Lq'], prec=6), 'unidades',
         'Promedio esperando servicio'],
        ['Tiempo en sistema', 'W',
         _fmt(mm1['W'], prec=8), 'segundos',
         'Tiempo total por solicitud'],
        ['Tiempo en cola', 'Wq',
         _fmt(mm1['Wq'], prec=8), 'segundos',
         'Espera antes de ser atendida'],
    ], [1.7*inch, 0.5*inch, 1.4*inch, 0.7*inch, 2.2*inch])

    # Colorear fila de ρ según estabilidad
    res_table.setStyle(TableStyle([
        ('TEXTCOLOR', (2, 1), (4, 1), stable_color),
        ('FONTNAME',  (2, 1), (4, 1), 'Helvetica-Bold'),
        ('FONTNAME',  (1, 1), (1, -1), 'Courier-Bold'),
    ]))

    story += [
        _section_bar("5.  Resultados del Modelo M/M/1", S),
        Spacer(1, 4),
        res_table,
        Spacer(1, 10),
    ]

    # ── SECCIÓN 6: ANÁLISIS E INTERPRETACIÓN ──────────────────────────────────
    if mm1['stable']:
        if rho_pct < 30:
            estado = (
                f"El sistema opera con utilización muy baja ({rho_pct:.2f}%). "
                "El CPU dispone de amplia capacidad libre; las solicitudes son "
                "atendidas prácticamente de inmediato y la cola es despreciable.")
        elif rho_pct < 60:
            estado = (
                f"El sistema opera en un rango saludable ({rho_pct:.2f}%). "
                "El CPU maneja la carga sin dificultad y los tiempos de espera "
                "son moderados. No se anticipan problemas de congestión.")
        elif rho_pct < 80:
            estado = (
                f"El sistema presenta utilización considerable ({rho_pct:.2f}%). "
                "La cola comienza a tener impacto apreciable. Se recomienda "
                "monitorear tendencias para anticipar saturación.")
        else:
            estado = (
                f"ADVERTENCIA: Utilización alta ({rho_pct:.2f}%). "
                "A medida que ρ se aproxima a 1.0 los tiempos de espera "
                "crecen de forma exponencial. Evalúe redistribuir la carga.")
    else:
        estado = (
            f"CRÍTICO: El sistema está saturado (ρ = {rho_pct:.2f}% ≥ 100%). "
            "Bajo M/M/1, un sistema saturado implica cola y tiempos de espera "
            "teóricamente ilimitados. Se requiere acción correctiva inmediata.")

    detail = ""
    if mm1['stable']:
        detail = (
            f"Con <b>{mm1['L']:.6f} solicitudes</b> promedio en el sistema "
            f"({mm1['Lq']:.6f} en cola), cada solicitud tarda en promedio "
            f"<b>{mm1['W']:.8f} s</b> dentro del sistema, de los cuales "
            f"<b>{mm1['Wq']:.8f} s</b> corresponden a espera en cola. "
            "Los valores de W y Wq son coherentes con las frecuencias de "
            "interrupción observadas, que ocurren en el orden de microsegundos.")

    story += [
        _section_bar("6.  Análisis e Interpretación", S),
        Spacer(1, 5),
        Paragraph(f"<b>Estado del sistema:</b>  {estado}", S['Body']),
        Spacer(1, 3),
    ]
    if detail:
        story += [Paragraph(detail, S['Body']), Spacer(1, 3)]

    story.append(Paragraph(
        "<b>Nota metodológica:</b>  Las interrupciones del CPU abarcan señales de "
        "hardware (controladores de disco, red, temporizadores del sistema) y de "
        "software (llamadas al sistema, excepciones).  El modelo M/M/1 asume "
        "llegadas Poisson y tiempos de servicio exponencialmente distribuidos, "
        "suposiciones que son una aproximación razonable para el flujo mixto de "
        "interrupciones en un sistema de uso general.  Los resultados representan "
        f"el comportamiento del CPU durante el intervalo de {metrics['interval']} s "
        "de muestreo y pueden variar según la carga de trabajo del momento.",
        S['Body']))

    # ── PIE DE PÁGINA ─────────────────────────────────────────────────────────
    story += [
        Spacer(1, 14),
        HRFlowable(width="100%", thickness=1, color=C_AZUL_OSCURO),
        Spacer(1, 4),
        Paragraph(
            f"Generado automáticamente  ·  {now.strftime('%d/%m/%Y  %H:%M:%S')}"
            f"  ·  Host: {sys_info['hostname']}",
            S['Small']),
        Paragraph(
            "PSWE-14 Ingeniería de Rendimiento de Sistemas  ·  Universidad Cenfotec",
            S['Small']),
    ]

    doc.build(story)
    return os.path.abspath(output_path)


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print("  PSWE-14 — Proyecto #1: Análisis de Rendimiento M/M/1")
    print("=" * 62)
    print("  Integrantes:")
    for m in GROUP_MEMBERS:
        print(f"    · {m}")
    print("=" * 62)

    # Paso 1: información del sistema
    print("\n[1/4] Obteniendo información del sistema...")
    sys_info = get_system_info()
    print(f"      Host : {sys_info['hostname']}")
    print(f"      SO   : {sys_info['os']}")
    print(f"      CPU  : {sys_info['cpu_freq_mhz']:.0f} MHz  "
          f"({sys_info['cpu_cores_logical']} núcleos lógicos)")
    print(f"      RAM  : {sys_info['ram_total_gb']:.1f} GB total  "
          f"({sys_info['ram_percent']:.1f}% en uso)")

    # Paso 2: medir λ y μ del SO
    print(f"\n[2/4] Midiendo lambda y mu del sistema operativo ({SAMPLING_SECONDS} s)...")
    metrics = measure_lambda_mu(SAMPLING_SECONDS)
    print(f"      lambda (tasa llegada) = {metrics['lambda']:>14,.2f}  interrupciones/s")
    print(f"      mu    (tasa servicio) = {metrics['mu']:>14,.2f}  interrupciones/s")
    print(f"      rho   (uso CPU)       = {metrics['cpu_percent']:>13.2f} %")
    print(f"      Interrupciones   = {metrics['interrupts_total']:>14,}")
    print(f"      Cambios contexto = {metrics['ctx_switches_per_s']:>14,.2f}  cambios/s")

    # Paso 3: calcular M/M/1
    print("\n[3/4] Calculando metricas M/M/1...")
    mm1 = calculate_mm1(metrics['lambda'], metrics['mu'])
    print(f"      rho = {mm1['rho']*100:.4f} %  "
          f"({'ESTABLE' if mm1['stable'] else 'SATURADO'})")
    print(f"      L   = {mm1['L']:.6f}  unidades")
    print(f"      Lq  = {mm1['Lq']:.6f}  unidades")
    if mm1['stable']:
        print(f"      W   = {mm1['W']:.8f}  segundos")
        print(f"      Wq  = {mm1['Wq']:.8f}  segundos")
    else:
        print("      W   = infinito  (sistema saturado)")
        print("      Wq  = infinito  (sistema saturado)")

    # Paso 4: generar PDF
    print(f"\n[4/4] Generando PDF: {OUTPUT_PDF} ...")
    pdf_path = generate_pdf(sys_info, metrics, mm1, OUTPUT_PDF)
    print(f"      PDF guardado en: {pdf_path}")

    print("\n" + "=" * 62)
    print("  ¡Análisis completado exitosamente!")
    print("=" * 62 + "\n")


if __name__ == '__main__':
    main()
