"""
Generate riders_giro2026_v1.json for Giro d'Italia 2026.

Layer 0 compliance:
- No race outcome data used (no finishing positions, stage results, time gaps)
- Specialist classifications derived from team role declarations and publicly
  available athlete profiles (body type, team announcements, specialist categories
  on procyclingstats.com and team press releases)
- Recovery dynamics set to status=unobserved for all riders — no physiological
  test data available in public domain
- Exclusion window: must exceed full race duration (~23 days); data retrieved
  before race start (May 9 2026), well outside exclusion window for stable
  career attributes
"""

import json
from datetime import datetime

PROVENANCE_SOURCE = (
    "procyclingstats.com specialist classifications; "
    "cyclinguptodate.com startlist (retrieved 2026-05-04); "
    "team press releases and role declarations; "
    "publicly available athlete physique profiles. "
    "NO race outcome data (finishing positions, time gaps, stage results) used."
)
RETRIEVED_AT = "2026-05-04T00:00:00Z"

# Specialty profile templates (Layer 0 compliant — no race outcome derivation)
PROFILES = {
    "gc_elite": {
        "physiological_capacity": {
            "sustained_power_proxy": "elite",
            "anaerobic_capacity": "medium",
            "fatigue_resistance": "elite",
        },
        "terrain_affinity": {"climbing": 0.90, "sprint": 0.20, "time_trial": 0.72, "mixed": 0.72},
        "consistency_profile": {"performance_variance": "low", "reliability": "high"},
        "recovery_dynamics": {"multi_stage_endurance": "elite", "status": "unobserved"},
    },
    "gc_high": {
        "physiological_capacity": {
            "sustained_power_proxy": "high",
            "anaerobic_capacity": "medium",
            "fatigue_resistance": "high",
        },
        "terrain_affinity": {"climbing": 0.78, "sprint": 0.22, "time_trial": 0.55, "mixed": 0.65},
        "consistency_profile": {"performance_variance": "low", "reliability": "high"},
        "recovery_dynamics": {"multi_stage_endurance": "high", "status": "unobserved"},
    },
    "gc_medium": {
        "physiological_capacity": {
            "sustained_power_proxy": "medium",
            "anaerobic_capacity": "medium",
            "fatigue_resistance": "medium",
        },
        "terrain_affinity": {"climbing": 0.65, "sprint": 0.25, "time_trial": 0.48, "mixed": 0.58},
        "consistency_profile": {"performance_variance": "medium", "reliability": "medium"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
    "tt_specialist": {
        "physiological_capacity": {
            "sustained_power_proxy": "elite",
            "anaerobic_capacity": "low",
            "fatigue_resistance": "high",
        },
        "terrain_affinity": {"climbing": 0.38, "sprint": 0.55, "time_trial": 0.92, "mixed": 0.52},
        "consistency_profile": {"performance_variance": "low", "reliability": "high"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
    "sprinter_tt": {
        # Milan-type: elite sprint AND elite TT
        "physiological_capacity": {
            "sustained_power_proxy": "high",
            "anaerobic_capacity": "elite",
            "fatigue_resistance": "medium",
        },
        "terrain_affinity": {"climbing": 0.28, "sprint": 0.92, "time_trial": 0.82, "mixed": 0.45},
        "consistency_profile": {"performance_variance": "low", "reliability": "high"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
    "sprinter_elite": {
        "physiological_capacity": {
            "sustained_power_proxy": "medium",
            "anaerobic_capacity": "elite",
            "fatigue_resistance": "medium",
        },
        "terrain_affinity": {"climbing": 0.18, "sprint": 0.92, "time_trial": 0.38, "mixed": 0.38},
        "consistency_profile": {"performance_variance": "medium", "reliability": "high"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
    "sprinter_high": {
        "physiological_capacity": {
            "sustained_power_proxy": "medium",
            "anaerobic_capacity": "high",
            "fatigue_resistance": "medium",
        },
        "terrain_affinity": {"climbing": 0.22, "sprint": 0.82, "time_trial": 0.38, "mixed": 0.40},
        "consistency_profile": {"performance_variance": "medium", "reliability": "medium"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
    "classics": {
        "physiological_capacity": {
            "sustained_power_proxy": "high",
            "anaerobic_capacity": "high",
            "fatigue_resistance": "high",
        },
        "terrain_affinity": {"climbing": 0.52, "sprint": 0.62, "time_trial": 0.40, "mixed": 0.72},
        "consistency_profile": {"performance_variance": "medium", "reliability": "medium"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
    "breakaway": {
        "physiological_capacity": {
            "sustained_power_proxy": "medium",
            "anaerobic_capacity": "high",
            "fatigue_resistance": "medium",
        },
        "terrain_affinity": {"climbing": 0.58, "sprint": 0.42, "time_trial": 0.42, "mixed": 0.62},
        "consistency_profile": {"performance_variance": "high", "reliability": "medium"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
    "climbing_dom": {
        "physiological_capacity": {
            "sustained_power_proxy": "medium",
            "anaerobic_capacity": "medium",
            "fatigue_resistance": "medium",
        },
        "terrain_affinity": {"climbing": 0.65, "sprint": 0.20, "time_trial": 0.42, "mixed": 0.55},
        "consistency_profile": {"performance_variance": "medium", "reliability": "medium"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
    "domestique": {
        "physiological_capacity": {
            "sustained_power_proxy": "medium",
            "anaerobic_capacity": "medium",
            "fatigue_resistance": "medium",
        },
        "terrain_affinity": {"climbing": 0.50, "sprint": 0.35, "time_trial": 0.42, "mixed": 0.52},
        "consistency_profile": {"performance_variance": "medium", "reliability": "medium"},
        "recovery_dynamics": {"multi_stage_endurance": "medium", "status": "unobserved"},
    },
}

# (rider_id, full_name, team, nationality, birth_year, specialty, terrain_affinity_override)
# terrain_affinity_override: dict of partial overrides, or None
RIDERS_RAW = [
    # --- Decathlon CMA CGM ---
    ("andresen_tobias", "Tobias Lund Andresen", "Decathlon CMA CGM", "DEN", 2002, "sprinter_high", None),
    ("gall_felix", "Felix Gall", "Decathlon CMA CGM", "AUT", 1998, "gc_high", {"climbing": 0.80, "time_trial": 0.58}),
    ("gudmestad_tord", "Tord Gudmestad", "Decathlon CMA CGM", "NOR", 2002, "climbing_dom", None),
    ("muhlberger_gregor", "Gregor Mühlberger", "Decathlon CMA CGM", "AUT", 1993, "climbing_dom", None),
    ("naesen_oliver", "Oliver Naesen", "Decathlon CMA CGM", "BEL", 1990, "classics", None),
    ("pedersen_rasmus", "Rasmus Søjberg Pedersen", "Decathlon CMA CGM", "DEN", 2001, "gc_medium", None),
    ("scotson_callum", "Callum Scotson", "Decathlon CMA CGM", "AUS", 1996, "domestique", {"time_trial": 0.68}),
    ("staunemittet_johannes", "Johannes Staune-Mittet", "Decathlon CMA CGM", "NOR", 2002, "gc_high", {"climbing": 0.76, "time_trial": 0.66}),

    # --- Netcompany INEOS ---
    ("arensman_thymen", "Thymen Arensman", "Netcompany INEOS", "NED", 2000, "gc_high", {"climbing": 0.76, "time_trial": 0.74}),
    ("bernal_egan", "Egan Bernal", "Netcompany INEOS", "COL", 1997, "gc_elite", {"climbing": 0.86, "time_trial": 0.62}),
    ("ganna_filippo", "Filippo Ganna", "Netcompany INEOS", "ITA", 1996, "tt_specialist", {"time_trial": 0.96, "climbing": 0.42, "sprint": 0.72}),
    ("haig_jack", "Jack Haig", "Netcompany INEOS", "AUS", 1993, "gc_medium", None),
    ("deplus_laurens", "Laurens De Plus", "Netcompany INEOS", "BEL", 1995, "climbing_dom", None),
    ("svestadbardseng_embret", "Embret Svestad-Bårdseng", "Netcompany INEOS", "NOR", 2003, "climbing_dom", None),
    ("swift_connor", "Connor Swift", "Netcompany INEOS", "GBR", 1994, "domestique", None),
    ("turner_ben", "Ben Turner", "Netcompany INEOS", "GBR", 2000, "gc_medium", None),

    # --- Tudor Pro Cycling ---
    ("barta_will", "Will Barta", "Tudor Pro Cycling", "USA", 1998, "climbing_dom", None),
    ("froideveaux_robin", "Robin Froideveaux", "Tudor Pro Cycling", "SUI", 2001, "domestique", None),
    ("mozzato_luca", "Luca Mozzato", "Tudor Pro Cycling", "ITA", 1998, "sprinter_high", {"sprint": 0.80}),
    ("rondel_mathys", "Mathys Rondel", "Tudor Pro Cycling", "FRA", 2001, "breakaway", None),
    ("storer_michael", "Michael Storer", "Tudor Pro Cycling", "AUS", 1997, "gc_medium", {"climbing": 0.68, "mixed": 0.62}),
    ("stork_florian", "Florian Stork", "Tudor Pro Cycling", "GER", 1996, "domestique", None),
    ("warbasse_larry", "Larry Warbasse", "Tudor Pro Cycling", "USA", 1990, "gc_medium", None),

    # --- Team Polti VisitMalta ---
    ("bais_mattia", "Mattia Bais", "Team Polti VisitMalta", "ITA", 1996, "breakaway", None),
    ("crescioli_ludovico", "Ludovico Crescioli", "Team Polti VisitMalta", "ITA", 2002, "climbing_dom", None),
    ("lonardi_giovanni", "Giovanni Lonardi", "Team Polti VisitMalta", "ITA", 1996, "sprinter_high", {"sprint": 0.80}),
    ("maestri_mirco", "Mirco Maestri", "Team Polti VisitMalta", "ITA", 1991, "climbing_dom", None),
    ("mifsud_andrea", "Andrea Mifsud", "Team Polti VisitMalta", "MLT", 2000, "domestique", None),
    ("pesenti_thomas", "Thomas Pesenti", "Team Polti VisitMalta", "ITA", 2000, "breakaway", None),
    ("sevilla_diego", "Diego Pablo Sevilla", "Team Polti VisitMalta", "COL", 2001, "climbing_dom", None),
    ("tonelli_alessandro", "Alessandro Tonelli", "Team Polti VisitMalta", "ITA", 1992, "domestique", None),

    # --- Bahrain Victorious ---
    ("buitrago_santiago", "Santiago Buitrago", "Bahrain Victorious", "COL", 2000, "gc_high", {"climbing": 0.80}),
    ("caruso_damiano", "Damiano Caruso", "Bahrain Victorious", "ITA", 1987, "gc_medium", {"climbing": 0.68}),
    ("eulalia_afonso", "Afonso Eulálio", "Bahrain Victorious", "POR", 2001, "climbing_dom", None),
    ("govekar_matevz", "Matevž Govekar", "Bahrain Victorious", "SLO", 2002, "gc_medium", None),
    ("miholjevic_fran", "Fran Miholjević", "Bahrain Victorious", "CRO", 2002, "climbing_dom", None),
    ("paasschens_mathijs", "Mathijs Paasschens", "Bahrain Victorious", "NED", 1996, "domestique", None),
    ("segaert_alec", "Alec Segaert", "Bahrain Victorious", "BEL", 2002, "tt_specialist", {"time_trial": 0.88, "climbing": 0.40}),
    ("zambanini_edoardo", "Edoardo Zambanini", "Bahrain Victorious", "ITA", 1999, "climbing_dom", None),

    # --- Uno-X Mobility ---
    ("blikra_erlend", "Erlend Blikra", "Uno-X Mobility", "NOR", 2001, "climbing_dom", None),
    ("dversnes_fredrik", "Fredrik Dversnes", "Uno-X Mobility", "NOR", 1999, "climbing_dom", None),
    ("hoelgaard_markus", "Markus Hoelgaard", "Uno-X Mobility", "NOR", 1994, "sprinter_high", None),
    ("holter_adne", "Ådne Holter", "Uno-X Mobility", "NOR", 1994, "climbing_dom", None),
    ("kulset_johannes", "Johannes Kulset", "Uno-X Mobility", "NOR", 2001, "breakaway", None),
    ("leknessund_andreas", "Andreas Leknessund", "Uno-X Mobility", "NOR", 1999, "gc_high", {"climbing": 0.74, "time_trial": 0.70}),
    ("loland_sakarias", "Sakarias Koller Løland", "Uno-X Mobility", "NOR", 2003, "climbing_dom", None),
    ("tjotta_martin", "Martin Tjøtta", "Uno-X Mobility", "NOR", 1999, "domestique", None),

    # --- NSN Cycling ---
    ("hirt_jan", "Jan Hirt", "NSN Cycling", "CZE", 1991, "gc_medium", {"climbing": 0.72}),
    ("mullen_ryan", "Ryan Mullen", "NSN Cycling", "IRL", 1994, "domestique", {"time_trial": 0.68}),
    ("pinarello_alessandro", "Alessandro Pinarello", "NSN Cycling", "ITA", 2002, "climbing_dom", None),
    ("schultz_nick", "Nick Schultz", "NSN Cycling", "AUS", 1994, "breakaway", None),
    ("smith_dion", "Dion Smith", "NSN Cycling", "NZL", 1993, "domestique", None),
    ("stewart_jake", "Jake Stewart", "NSN Cycling", "GBR", 2000, "sprinter_high", {"sprint": 0.78}),
    ("strong_corbin", "Corbin Strong", "NSN Cycling", "NZL", 2000, "sprinter_high", {"sprint": 0.80}),
    ("vernon_ethan", "Ethan Vernon", "NSN Cycling", "GBR", 2000, "domestique", None),

    # --- Pinarello Q36.5 ---
    ("bax_sjoerd", "Sjoerd Bax", "Pinarello Q36.5", "NED", 1997, "domestique", None),
    ("christen_fabio", "Fabio Christen", "Pinarello Q36.5", "SUI", 1999, "domestique", None),
    ("delacruz_david", "David De La Cruz", "Pinarello Q36.5", "ESP", 1989, "gc_medium", None),
    ("donovan_mark", "Mark Donovan", "Pinarello Q36.5", "GBR", 2000, "domestique", None),
    ("gonzalez_david", "David González", "Pinarello Q36.5", "ESP", 1998, "climbing_dom", None),
    ("harper_chris", "Chris Harper", "Pinarello Q36.5", "AUS", 1994, "domestique", None),
    ("moschetti_matteo", "Matteo Moschetti", "Pinarello Q36.5", "ITA", 1996, "sprinter_high", None),
    ("zukowsky_nick", "Nick Zukowsky", "Pinarello Q36.5", "CAN", 1999, "domestique", None),

    # --- Lidl-Trek ---
    ("ciccone_giulio", "Giulio Ciccone", "Lidl-Trek", "ITA", 1994, "gc_medium", {"climbing": 0.76, "sprint": 0.30}),
    ("consonni_simone", "Simone Consonni", "Lidl-Trek", "ITA", 1994, "sprinter_high", {"sprint": 0.80}),
    ("geewest_derek", "Derek Gee-West", "Lidl-Trek", "USA", 1999, "domestique", None),
    ("ghebreigzabhier_amanuel", "Amanuel Ghebreigzabhier", "Lidl-Trek", "ERI", 1994, "climbing_dom", None),
    ("milan_jonathan", "Jonathan Milan", "Lidl-Trek", "ITA", 2000, "sprinter_tt", None),
    ("sobrero_matteo", "Matteo Sobrero", "Lidl-Trek", "ITA", 1999, "gc_medium", {"time_trial": 0.65}),
    ("teutenberg_tim", "Tim Torn Teutenberg", "Lidl-Trek", "GER", 2001, "breakaway", None),
    ("walscheid_max", "Max Walscheid", "Lidl-Trek", "GER", 1993, "sprinter_high", {"sprint": 0.82}),

    # --- Alpecin-Premier Tech ---
    ("bayer_tobias", "Tobias Bayer", "Alpecin-Premier Tech", "AUT", 2002, "sprinter_high", {"sprint": 0.84, "climbing": 0.32}),
    ("busatto_francesco", "Francesco Busatto", "Alpecin-Premier Tech", "ITA", 1997, "domestique", None),
    ("geens_jonas", "Jonas Geens", "Alpecin-Premier Tech", "BEL", 1994, "domestique", None),
    ("groves_kaden", "Kaden Groves", "Alpecin-Premier Tech", "AUS", 1998, "sprinter_high", {"sprint": 0.85}),
    ("planckaert_edward", "Edward Planckaert", "Alpecin-Premier Tech", "BEL", 1988, "sprinter_high", None),
    ("plowright_jensen", "Jensen Plowright", "Alpecin-Premier Tech", "AUS", 1997, "climbing_dom", None),
    ("pricepejtersen_johan", "Johan Price-Pejtersen", "Alpecin-Premier Tech", "DEN", 2002, "gc_medium", {"time_trial": 0.65}),
    ("vergallito_luca", "Luca Vergallito", "Alpecin-Premier Tech", "ITA", 2002, "domestique", None),

    # --- Team Jayco AlUla ---
    ("ackermann_pascal", "Pascal Ackermann", "Team Jayco AlUla", "GER", 1994, "sprinter_high", {"sprint": 0.85}),
    ("bouwman_koen", "Koen Bouwman", "Team Jayco AlUla", "NED", 1994, "breakaway", {"climbing": 0.68}),
    ("donaldson_robert", "Robert Donaldson", "Team Jayco AlUla", "GBR", 2002, "climbing_dom", None),
    ("engelhardt_felix", "Felix Engelhardt", "Team Jayco AlUla", "GER", 1999, "climbing_dom", None),
    ("hatherly_alan", "Alan Hatherly", "Team Jayco AlUla", "RSA", 1997, "climbing_dom", None),
    ("juuljensen_chris", "Chris Juul-Jensen", "Team Jayco AlUla", "DEN", 1989, "domestique", None),
    ("oconnor_ben", "Ben O'Connor", "Team Jayco AlUla", "AUS", 1995, "gc_high", {"climbing": 0.80}),
    ("vendrame_andrea", "Andrea Vendrame", "Team Jayco AlUla", "ITA", 1994, "breakaway", None),

    # --- Red Bull BORA hansgrohe ---
    ("aleotti_giovanni", "Giovanni Aleotti", "Red Bull BORA hansgrohe", "ITA", 2000, "gc_medium", {"climbing": 0.72}),
    ("vandijke_mick", "Mick van Dijke", "Red Bull BORA hansgrohe", "NED", 2000, "domestique", None),
    ("hindley_jai", "Jai Hindley", "Red Bull BORA hansgrohe", "AUS", 1996, "gc_high", {"climbing": 0.82}),
    ("moscon_gianni", "Gianni Moscon", "Red Bull BORA hansgrohe", "ITA", 1994, "classics", None),
    ("pellizzari_giulio", "Giulio Pellizzari", "Red Bull BORA hansgrohe", "ITA", 2003, "gc_elite", {"climbing": 0.88, "time_trial": 0.62}),
    ("vlasov_aleksandr", "Aleksandr Vlasov", "Red Bull BORA hansgrohe", "RUS", 1998, "gc_high", {"climbing": 0.76}),
    ("zwiehoff_ben", "Ben Zwiehoff", "Red Bull BORA hansgrohe", "GER", 1994, "domestique", None),

    # --- XDS Astana ---
    ("ballerini_davide", "Davide Ballerini", "XDS Astana", "ITA", 1994, "sprinter_high", {"sprint": 0.80, "mixed": 0.55}),
    ("bettiol_alberto", "Alberto Bettiol", "XDS Astana", "ITA", 1993, "classics", None),
    ("livyns_arjen", "Arjen Livyns", "XDS Astana", "BEL", 1994, "domestique", None),
    ("lopez_harold", "Harold Martin Lopez", "XDS Astana", "COL", 1997, "gc_medium", {"climbing": 0.74}),
    ("malucelli_matteo", "Matteo Malucelli", "XDS Astana", "ITA", 1993, "sprinter_high", None),
    ("scaroni_christian", "Christian Scaroni", "XDS Astana", "ITA", 1994, "breakaway", None),
    ("silva_thomas", "Thomas Silva", "XDS Astana", "POR", 2001, "climbing_dom", None),
    ("ulissi_diego", "Diego Ulissi", "XDS Astana", "ITA", 1989, "gc_medium", {"climbing": 0.65}),

    # --- EF Education EasyPost ---
    ("battistella_samuele", "Samuele Battistella", "EF Education EasyPost", "ITA", 1998, "breakaway", None),
    ("cepeda_alexander", "Alexander Cepeda", "EF Education EasyPost", "ECU", 2000, "gc_high", {"climbing": 0.78}),
    ("vanderlee_jardi", "Jardi van der Lee", "EF Education EasyPost", "NED", 1997, "climbing_dom", None),
    ("mihkels_madis", "Madis Mihkels", "EF Education EasyPost", "EST", 2002, "sprinter_high", {"sprint": 0.82}),
    ("quinn_sean", "Sean Quinn", "EF Education EasyPost", "USA", 1999, "climbing_dom", None),
    ("rafferty_darren", "Darren Rafferty", "EF Education EasyPost", "IRL", 1996, "domestique", None),
    ("shaw_james", "James Shaw", "EF Education EasyPost", "GBR", 1994, "domestique", None),
    ("valgren_michael", "Michael Valgren", "EF Education EasyPost", "DEN", 1992, "classics", None),

    # --- Team Picnic PostNL ---
    ("vandenbroek_frank", "Frank van den Broek", "Team Picnic PostNL", "NED", 1997, "domestique", None),
    ("flynn_sean", "Sean Flynn", "Team Picnic PostNL", "USA", 2000, "climbing_dom", None),
    ("hamilton_chris", "Chris Hamilton", "Team Picnic PostNL", "AUS", 1995, "gc_medium", {"climbing": 0.72}),
    ("dejong_timo", "Timo de Jong", "Team Picnic PostNL", "NED", 2003, "domestique", None),
    ("knox_james", "James Knox", "Team Picnic PostNL", "GBR", 1995, "gc_medium", {"climbing": 0.70}),
    ("leemreize_gijs", "Gijs Leemreize", "Team Picnic PostNL", "NED", 1999, "gc_medium", {"climbing": 0.70}),
    ("naberman_tim", "Tim Naberman", "Team Picnic PostNL", "NED", 2001, "climbing_dom", None),
    ("vanuden_casper", "Casper van Uden", "Team Picnic PostNL", "NED", 2001, "domestique", None),

    # --- Lotto-Intermarché ---
    ("aerts_toon", "Toon Aerts", "Lotto-Intermarché", "BEL", 1993, "classics", None),
    ("debuyst_jasper", "Jasper De Buyst", "Lotto-Intermarché", "BEL", 1993, "domestique", None),
    ("vaneetvelt_lennert", "Lennert Van Eetvelt", "Lotto-Intermarché", "BEL", 2002, "gc_high", {"climbing": 0.78}),
    ("gualdi_simone", "Simone Gualdi", "Lotto-Intermarché", "ITA", 2001, "climbing_dom", None),
    ("delie_arnaud", "Arnaud De Lie", "Lotto-Intermarché", "BEL", 2002, "sprinter_elite", {"sprint": 0.88, "climbing": 0.22}),
    ("rota_lorenzo", "Lorenzo Rota", "Lotto-Intermarché", "ITA", 1995, "breakaway", {"climbing": 0.65}),
    ("rutsch_jonas", "Jonas Rutsch", "Lotto-Intermarché", "GER", 1998, "climbing_dom", None),
    ("slock_liam", "Liam Slock", "Lotto-Intermarché", "BEL", 2002, "climbing_dom", None),

    # --- Team Visma Lease a Bike ---
    ("campenaerts_victor", "Victor Campenaerts", "Team Visma Lease a Bike", "BEL", 1991, "tt_specialist", {"time_trial": 0.92, "climbing": 0.30}),
    ("kelderman_wilco", "Wilco Kelderman", "Team Visma Lease a Bike", "NED", 1991, "gc_medium", None),
    ("kielich_timo", "Timo Kielich", "Team Visma Lease a Bike", "BEL", 2000, "climbing_dom", None),
    ("kuss_sepp", "Sepp Kuss", "Team Visma Lease a Bike", "USA", 1994, "gc_high", {"climbing": 0.80, "time_trial": 0.52}),
    ("lemmen_bart", "Bart Lemmen", "Team Visma Lease a Bike", "NED", 1999, "climbing_dom", None),
    ("piganzoli_davide", "Davide Piganzoli", "Team Visma Lease a Bike", "ITA", 2002, "gc_medium", {"climbing": 0.70}),
    ("rex_tim", "Tim Rex", "Team Visma Lease a Bike", "DEN", 2001, "domestique", None),
    ("vingegaard_jonas", "Jonas Vingegaard", "Team Visma Lease a Bike", "DEN", 1996, "gc_elite", {"climbing": 0.92, "time_trial": 0.85}),

    # --- Soudal Quick-Step ---
    ("bastiaens_ayco", "Ayco Bastiaens", "Soudal Quick-Step", "BEL", 2001, "domestique", None),
    ("vangestel_dries", "Dries Van Gestel", "Soudal Quick-Step", "BEL", 1993, "classics", None),
    ("magnier_paul", "Paul Magnier", "Soudal Quick-Step", "FRA", 2003, "breakaway", {"sprint": 0.55}),
    ("raccagni_andrea", "Andrea Raccagni", "Soudal Quick-Step", "ITA", 2004, "climbing_dom", None),
    ("stuyven_jasper", "Jasper Stuyven", "Soudal Quick-Step", "BEL", 1992, "classics", {"sprint": 0.75, "climbing": 0.32}),
    ("zana_filippo", "Filippo Zana", "Soudal Quick-Step", "ITA", 1998, "gc_high", {"climbing": 0.75}),

    # --- UAE Team Emirates XRG ---
    ("arrieta_igor", "Igor Arrieta", "UAE Team Emirates XRG", "ESP", 2002, "gc_medium", {"climbing": 0.68}),
    ("christen_jan", "Jan Christen", "UAE Team Emirates XRG", "SUI", 2003, "climbing_dom", None),
    ("morgado_antonio", "António Morgado", "UAE Team Emirates XRG", "POR", 2003, "gc_medium", {"climbing": 0.68}),
    ("narvaez_jhonatan", "Jhonatan Narváez", "UAE Team Emirates XRG", "ECU", 1997, "gc_medium", {"climbing": 0.65, "time_trial": 0.60}),
    ("soler_marc", "Marc Soler", "UAE Team Emirates XRG", "ESP", 1993, "gc_medium", {"climbing": 0.68}),
    ("vine_jay", "Jay Vine", "UAE Team Emirates XRG", "AUS", 1995, "gc_high", {"climbing": 0.80}),
    ("yates_adam", "Adam Yates", "UAE Team Emirates XRG", "GBR", 1992, "gc_high", {"climbing": 0.80}),

    # --- Groupama FDJ United ---
    ("barthe_cyril", "Cyril Barthe", "Groupama FDJ United", "FRA", 1995, "climbing_dom", None),
    ("cavagna_remi", "Rémi Cavagna", "Groupama FDJ United", "FRA", 1995, "breakaway", {"time_trial": 0.65}),
    ("huens_axel", "Axel Huens", "Groupama FDJ United", "BEL", 2001, "climbing_dom", None),
    ("jacobs_johan", "Johan Jacobs", "Groupama FDJ United", "BEL", 1994, "domestique", None),
    ("kench_josh", "Josh Kench", "Groupama FDJ United", "NZL", 1999, "climbing_dom", None),
    ("penhoet_paul", "Paul Penhoët", "Groupama FDJ United", "FRA", 1999, "climbing_dom", None),
    ("rochas_remy", "Rémy Rochas", "Groupama FDJ United", "FRA", 1994, "gc_medium", None),
    ("rolland_brieuc", "Brieuc Rolland", "Groupama FDJ United", "FRA", 1994, "breakaway", None),

    # --- Bardiani CSF 7 Saber ---
    ("magli_filippo", "Filippo Magli", "Bardiani CSF 7 Saber", "ITA", 2002, "climbing_dom", None),
    ("marcellusi_martin", "Martin Marcellusi", "Bardiani CSF 7 Saber", "ITA", 2001, "climbing_dom", None),
    ("paletti_luca", "Luca Paletti", "Bardiani CSF 7 Saber", "ITA", 2001, "domestique", None),
    ("rojas_vicente", "Vicente Rojas", "Bardiani CSF 7 Saber", "COL", 1998, "climbing_dom", None),
    ("tarozzi_manuele", "Manuele Tarozzi", "Bardiani CSF 7 Saber", "ITA", 2001, "domestique", None),
    ("tsvetkov_nikita", "Nikita Tsvetkov", "Bardiani CSF 7 Saber", "RUS", 1998, "climbing_dom", None),
    ("turconi_filippo", "Filippo Turconi", "Bardiani CSF 7 Saber", "ITA", 2001, "domestique", None),
    ("zanoncello_enrico", "Enrico Zanoncello", "Bardiani CSF 7 Saber", "ITA", 2003, "sprinter_high", {"sprint": 0.78}),

    # --- Movistar Team ---
    ("aular_orluis", "Orluis Aular", "Movistar Team", "VEN", 1996, "breakaway", None),
    ("garciacortina_ivan", "Iván García Cortina", "Movistar Team", "ESP", 1995, "classics", None),
    ("lopez_juanpe", "Juanpe Lopez", "Movistar Team", "ESP", 1993, "climbing_dom", {"climbing": 0.68}),
    ("mas_enric", "Enric Mas", "Movistar Team", "ESP", 1995, "gc_high", {"climbing": 0.80}),
    ("milesi_lorenzo", "Lorenzo Milesi", "Movistar Team", "ITA", 2001, "gc_medium", {"climbing": 0.68}),
    ("oliveira_nelson", "Nelson Oliveira", "Movistar Team", "POR", 1989, "domestique", {"time_trial": 0.62}),
    ("romo_javier", "Javier Romo", "Movistar Team", "ESP", 1997, "climbing_dom", None),
    ("rubio_einer", "Einer Rubio", "Movistar Team", "COL", 1998, "gc_medium", {"climbing": 0.72}),

    # --- Unibet Rose Rockets ---
    ("feldmann_karsten", "Karsten Larsen Feldmann", "Unibet Rose Rockets", "DEN", 1998, "climbing_dom", None),
    ("groenewegen_dylan", "Dylan Groenewegen", "Unibet Rose Rockets", "NED", 1993, "sprinter_elite", {"sprint": 0.92}),
    ("kopecky_tomas", "Tomáš Kopecký", "Unibet Rose Rockets", "SVK", 2003, "domestique", None),
    ("kubis_lukas", "Lukáš Kubiš", "Unibet Rose Rockets", "SVK", 1999, "climbing_dom", None),
    ("larsen_niklas", "Niklas Larsen", "Unibet Rose Rockets", "DEN", 1997, "domestique", None),
    ("poels_wout", "Wout Poels", "Unibet Rose Rockets", "NED", 1987, "climbing_dom", {"climbing": 0.70}),
    ("reinders_elmar", "Elmar Reinders", "Unibet Rose Rockets", "NED", 1994, "domestique", None),
    ("devries_hartthijs", "Hartthijs de Vries", "Unibet Rose Rockets", "NED", 2001, "domestique", None),
]


def build_rider(rider_id, name, team, nationality, birth_year, specialty, overrides):
    age = 2026 - birth_year
    profile = {k: v for k, v in PROFILES[specialty].items()}

    # Deep-copy and apply terrain_affinity overrides
    terrain = dict(profile["terrain_affinity"])
    if overrides:
        terrain.update(overrides)

    return {
        "rider_id": rider_id,
        "name": name,
        "team": team,
        "nationality": nationality,
        "age": age,
        "data_version": "v1",
        "exclusion_window_compliant": True,
        "provenance": {
            "source": PROVENANCE_SOURCE,
            "retrieved_at": RETRIEVED_AT,
        },
        "physiological_capacity": profile["physiological_capacity"],
        "terrain_affinity": terrain,
        "consistency_profile": profile["consistency_profile"],
        "recovery_dynamics": profile["recovery_dynamics"],
    }


def main():
    riders = []
    for row in RIDERS_RAW:
        rider_id, name, team, nationality, birth_year, specialty, overrides = row
        riders.append(build_rider(rider_id, name, team, nationality, birth_year, specialty, overrides))

    output = {
        "meta": {
            "race": "giro2026",
            "data_version": "v1",
            "rider_count": len(riders),
            "generated_at": RETRIEVED_AT,
            "layer": "Layer 0 — Rider-Intrinsic",
            "compliance_note": (
                "All attributes derived from non-race-outcome sources only. "
                "No finishing positions, time gaps, stage results, or race-derived metrics used. "
                "Specialist classifications based on team role declarations and publicly available "
                "athlete profiles. Recovery dynamics set to unobserved for all riders — "
                "no physiological test data available in public domain."
            ),
        },
        "riders": riders,
    }

    out_path = "data/riders/riders_giro2026_v1.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Generated {out_path} with {len(riders)} riders")


if __name__ == "__main__":
    main()
