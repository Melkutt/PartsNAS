"""Map a supplier's category string (e.g. Mouser "Multilayer Ceramic Capacitors
MLCC - SMD/SMT") onto a node in our own category tree.

Keyword rules first (a set of hint tokens -> one of our leaf category names),
then a token-overlap fallback. Returns {id, path, score} or None.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category
from .services import category_path_map

_STOP = {
    "smd", "smt", "tht", "surface", "mount", "mounting", "leaded", "chip", "fixed",
    "and", "or", "the", "of", "for", "with", "type", "types", "general", "purpose",
    "standard", "through", "hole", "pcb", "board", "parts", "products", "device",
    "devices", "components", "component", "embedded", "single", "ics", "ic",
    "integrated", "circuits", "circuit", "discrete", "semiconductor", "semiconductors",
    "arrays", "array", "coils", "chokes", "supplies",
}
_split = re.compile(r"[^a-z0-9]+")


def _tokens(s: str) -> list[str]:
    return [t for t in _split.split((s or "").lower()) if t and t not in _STOP and len(t) > 1]


# (required hint tokens, subset) -> our category name (leaf)
RULES: list[tuple[frozenset[str], str]] = [
    (frozenset({"ceramic", "capacitor"}), "Ceramic"),
    (frozenset({"ceramic", "capacitors"}), "Ceramic"),
    (frozenset({"mlcc"}), "Ceramic"),
    (frozenset({"aluminum", "electrolytic"}), "Electrolytic (Al)"),
    (frozenset({"aluminium", "electrolytic"}), "Electrolytic (Al)"),
    (frozenset({"electrolytic"}), "Electrolytic (Al)"),
    (frozenset({"tantalum"}), "Tantalum"),
    (frozenset({"film", "capacitor"}), "Film"),
    (frozenset({"film", "capacitors"}), "Film"),
    (frozenset({"supercapacitor"}), "Supercapacitor"),
    (frozenset({"supercapacitors"}), "Supercapacitor"),
    (frozenset({"thin", "film", "resistor"}), "Thin film"),
    (frozenset({"thin", "film", "resistors"}), "Thin film"),
    (frozenset({"thick", "film", "resistor"}), "Thick film"),
    (frozenset({"thick", "film", "resistors"}), "Thick film"),
    (frozenset({"resistor"}), "Thick film"),
    (frozenset({"resistors"}), "Thick film"),
    (frozenset({"wirewound"}), "Wirewound"),
    (frozenset({"resistor", "network"}), "Resistor network"),
    (frozenset({"potentiometer"}), "Potentiometer"),
    (frozenset({"potentiometers"}), "Potentiometer"),
    (frozenset({"trimmer"}), "Potentiometer"),
    (frozenset({"power", "inductor"}), "Power inductor"),
    (frozenset({"power", "inductors"}), "Power inductor"),
    (frozenset({"inductor"}), "Inductor"),
    (frozenset({"inductors"}), "Inductor"),
    (frozenset({"ferrite", "bead"}), "Ferrite bead"),
    (frozenset({"ferrite", "beads"}), "Ferrite bead"),
    (frozenset({"zener"}), "Zener diode"),
    (frozenset({"schottky"}), "Schottky"),
    (frozenset({"tvs"}), "TVS diode"),
    (frozenset({"esd"}), "TVS diode"),
    (frozenset({"rectifier"}), "Rectifier diode"),
    (frozenset({"rectifiers"}), "Rectifier diode"),
    (frozenset({"led"}), "LED"),
    (frozenset({"leds"}), "LED"),
    (frozenset({"varactor"}), "Varicap"),
    (frozenset({"varicap"}), "Varicap"),
    (frozenset({"mosfet"}), "MOSFET N-ch"),
    (frozenset({"mosfets"}), "MOSFET N-ch"),
    (frozenset({"igbt"}), "IGBT"),
    (frozenset({"igbts"}), "IGBT"),
    (frozenset({"bipolar", "transistor"}), "BJT NPN"),
    (frozenset({"bipolar", "transistors"}), "BJT NPN"),
    (frozenset({"bjt"}), "BJT NPN"),
    (frozenset({"triac"}), "TRIAC"),
    (frozenset({"triacs"}), "TRIAC"),
    (frozenset({"thyristor"}), "Thyristor (SCR)"),
    (frozenset({"scr"}), "Thyristor (SCR)"),
    (frozenset({"crystal"}), "Crystal (passive)"),
    (frozenset({"crystals"}), "Crystal (passive)"),
    (frozenset({"resonator"}), "Crystal (passive)"),
    (frozenset({"oscillator"}), "Oscillator (active)"),
    (frozenset({"oscillators"}), "Oscillator (active)"),
    (frozenset({"tcxo"}), "TCXO / VCTCXO"),
    (frozenset({"vctcxo"}), "TCXO / VCTCXO"),
    (frozenset({"microcontroller"}), "MCU / Microcontroller"),
    (frozenset({"microcontrollers"}), "MCU / Microcontroller"),
    (frozenset({"microprocessor"}), "MCU / Microcontroller"),
    (frozenset({"microprocessors"}), "MCU / Microcontroller"),
    (frozenset({"mcu"}), "MCU / Microcontroller"),
    (frozenset({"fpga"}), "MCU / Microcontroller"),
    (frozenset({"fpgas"}), "MCU / Microcontroller"),
    (frozenset({"cpld"}), "MCU / Microcontroller"),
    (frozenset({"dsp"}), "MCU / Microcontroller"),
    (frozenset({"op", "amp"}), "Op-amp"),
    (frozenset({"op", "amps"}), "Op-amp"),
    (frozenset({"operational", "amplifier"}), "Op-amp"),
    (frozenset({"operational", "amplifiers"}), "Op-amp"),
    (frozenset({"comparator"}), "Comparator"),
    (frozenset({"comparators"}), "Comparator"),
    (frozenset({"voltage", "reference"}), "Voltage reference"),
    (frozenset({"voltage", "references"}), "Voltage reference"),
    (frozenset({"ldo"}), "LDO / Voltage regulator"),
    (frozenset({"linear", "regulator"}), "LDO / Voltage regulator"),
    (frozenset({"linear", "regulators"}), "LDO / Voltage regulator"),
    (frozenset({"switching", "regulator"}), "DC/DC converter"),
    (frozenset({"switching", "regulators"}), "DC/DC converter"),
    (frozenset({"buck"}), "DC/DC converter"),
    (frozenset({"boost"}), "DC/DC converter"),
    (frozenset({"motor", "driver"}), "Motor driver"),
    (frozenset({"motor", "drivers"}), "Motor driver"),
    (frozenset({"gate"}), "Logic (gate, buffer, FF)"),
    (frozenset({"logic"}), "Logic (gate, buffer, FF)"),
    (frozenset({"flip", "flop"}), "Logic (gate, buffer, FF)"),
    (frozenset({"eeprom"}), "Memory (Flash, EEPROM, RAM)"),
    (frozenset({"flash", "memory"}), "Memory (Flash, EEPROM, RAM)"),
    (frozenset({"sram"}), "Memory (Flash, EEPROM, RAM)"),
    (frozenset({"sensor"}), "Sensor"),
    (frozenset({"sensors"}), "Sensor"),
    (frozenset({"accelerometer"}), "Sensor"),
    (frozenset({"accelerometers"}), "Sensor"),
    (frozenset({"gyroscope"}), "Sensor"),
    (frozenset({"temperature", "sensors"}), "Sensor"),
    (frozenset({"eeprom"}), "Memory (Flash, EEPROM, RAM)"),
    (frozenset({"flash"}), "Memory (Flash, EEPROM, RAM)"),
    (frozenset({"sram"}), "Memory (Flash, EEPROM, RAM)"),
    (frozenset({"fram"}), "Memory (Flash, EEPROM, RAM)"),
    (frozenset({"memory"}), "Memory (Flash, EEPROM, RAM)"),
    (frozenset({"instrumentation", "amplifiers"}), "Op-amp"),
    (frozenset({"buffer", "amplifiers"}), "Op-amp"),
    (frozenset({"current", "sense", "amplifiers"}), "Op-amp"),
    (frozenset({"amplifiers"}), "Op-amp"),
    (frozenset({"regulators", "linear"}), "LDO / Voltage regulator"),
    (frozenset({"regulators", "switching"}), "DC/DC converter"),
    (frozenset({"led", "drivers"}), "Motor driver"),
    (frozenset({"gate", "drivers"}), "Motor driver"),
    (frozenset({"clock", "generators"}), "Oscillator (active)"),
    (frozenset({"clock", "buffers"}), "Oscillator (active)"),
    (frozenset({"rtc"}), "MCU / Microcontroller"),
    (frozenset({"adc"}), "Voltage reference"),
    (frozenset({"dac"}), "Voltage reference"),
    (frozenset({"analog", "digital", "converters"}), "Voltage reference"),
    (frozenset({"transceiver"}), "Interface (USB, CAN, RS485)"),
    (frozenset({"transceivers"}), "Interface (USB, CAN, RS485)"),
    (frozenset({"drivers", "receivers"}), "Interface (USB, CAN, RS485)"),
    (frozenset({"rs232"}), "Interface (USB, CAN, RS485)"),
    (frozenset({"rs485"}), "Interface (USB, CAN, RS485)"),
    (frozenset({"can"}), "Interface (USB, CAN, RS485)"),
    (frozenset({"ethernet"}), "Interface (USB, CAN, RS485)"),
    (frozenset({"rf", "transceiver"}), "RF – Transceiver"),
    (frozenset({"bluetooth"}), "RF – Transceiver"),
    (frozenset({"gates", "inverters"}), "Logic (gate, buffer, FF)"),
    (frozenset({"buffers", "drivers"}), "Logic (gate, buffer, FF)"),
    (frozenset({"flip", "flops"}), "Logic (gate, buffer, FF)"),
    (frozenset({"jfet"}), "MOSFET N-ch"),
    (frozenset({"fets"}), "MOSFET N-ch"),
    (frozenset({"single", "bipolar"}), "BJT NPN"),
    (frozenset({"schottky", "diodes"}), "Schottky"),
    (frozenset({"tvs", "diodes"}), "TVS diode"),
    (frozenset({"zener", "diodes"}), "Zener diode"),
    (frozenset({"varistor"}), "Varistor (MOV)"),
    (frozenset({"varistors"}), "Varistor (MOV)"),
    (frozenset({"mov"}), "Varistor (MOV)"),
    (frozenset({"thermistor"}), "Thermistor (NTC / PTC)"),
    (frozenset({"thermistors"}), "Thermistor (NTC / PTC)"),
    (frozenset({"ntc"}), "Thermistor (NTC / PTC)"),
    (frozenset({"ptc"}), "Thermistor (NTC / PTC)"),
    (frozenset({"fuse"}), "Fuse"),
    (frozenset({"fuses"}), "Fuse"),
    (frozenset({"header"}), "Pin header / Socket"),
    (frozenset({"headers"}), "Pin header / Socket"),
    (frozenset({"socket"}), "Pin header / Socket"),
    (frozenset({"sockets"}), "Pin header / Socket"),
    (frozenset({"terminal", "block"}), "Terminal block"),
    (frozenset({"terminal", "blocks"}), "Terminal block"),
    (frozenset({"sub"}), "D-Sub"),
    (frozenset({"usb"}), "USB"),
    (frozenset({"sma"}), "SMA"),
    (frozenset({"bnc"}), "BNC"),
    (frozenset({"screw"}), "Screw & Nut"),
    (frozenset({"screws"}), "Screw & Nut"),
    (frozenset({"standoff"}), "Standoff"),
    (frozenset({"standoffs"}), "Standoff"),
    (frozenset({"spacer"}), "Standoff"),
    (frozenset({"spacers"}), "Standoff"),
    (frozenset({"heatsink"}), "Heatsink"),
    (frozenset({"heatsinks"}), "Heatsink"),
    (frozenset({"enclosure"}), "Enclosure / Box"),
    (frozenset({"enclosures"}), "Enclosure / Box"),
]


# strong signals that live in the *attributes*, not the category string
# (e.g. Digi-Key gives "Capacitors" generic but "Mounting Type: MLCC" pins it)
ATTR_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bMLCC\b|multilayer ceramic", re.I), "Ceramic"),
    (re.compile(r"\btantalum\b", re.I), "Tantalum"),
    (re.compile(r"alumin[iu]{1,2}m\s+electrolytic", re.I), "Electrolytic (Al)"),
    (re.compile(r"supercap|\bEDLC\b|double.?layer", re.I), "Supercapacitor"),
    (re.compile(r"\b(?:film|polyester|polypropylene|PPS|PEN)\s+cap", re.I), "Film"),
]


def match_category(db: Session, hint: str | None, attrs: dict | None = None) -> dict | None:
    paths = category_path_map(db)
    by_name: dict[str, list[int]] = {}
    for cid, name in db.execute(select(Category.id, Category.name)).all():
        by_name.setdefault(name.lower(), []).append(cid)

    def resolve(target: str, score: float):
        for cid in by_name.get(target.lower(), []):
            return {"id": cid, "path": paths.get(cid, target), "score": score}
        return None

    # attribute-based override first — a specific spec beats a vague category string
    if attrs:
        blob = " ".join(f"{k} {v}" for k, v in attrs.items())
        for rx, target in ATTR_RULES:
            if rx.search(blob):
                hit = resolve(target, 0.95)
                if hit:
                    return hit

    if not hint or not hint.strip():
        return None
    toks = set(_tokens(hint))
    if not toks:
        return None

    # rule pass — pick the most specific (largest) satisfied rule
    best_rule: tuple[int, str] | None = None
    for req, target in RULES:
        if req <= toks:
            if best_rule is None or len(req) > best_rule[0]:
                best_rule = (len(req), target)
    if best_rule:
        for cid in by_name.get(best_rule[1].lower(), []):
            return {"id": cid, "path": paths.get(cid, best_rule[1]), "score": 0.9}

    # fallback: token overlap against every category name (+ its ancestors)
    best: tuple[float, int] | None = None
    for cid, path in paths.items():
        cat_toks = set(_tokens(path))
        if not cat_toks:
            continue
        overlap = len(toks & cat_toks)
        if not overlap:
            continue
        score = overlap / len(toks | cat_toks) + 0.05 * path.count(">")  # prefer deeper
        if best is None or score > best[0]:
            best = (score, cid)
    if best and best[0] >= 0.28:
        return {"id": best[1], "path": paths.get(best[1], ""), "score": round(best[0], 2)}
    return None
