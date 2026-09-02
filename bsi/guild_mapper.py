"""
bsi/guild_mapper.py
Mapping van Latijnse vogelnamen naar gilde-categorieën en vliegstrategieën.
"""

from enum import Enum
from typing import Optional


class FlightStrategy(Enum):
    THERMAL = "Thermal"  # Zwevers (Ooievaar, Buizerd, Wespendief)
    ACTIVE = "Active"    # Actieve vliegers (Reigers, Kiekendieven, Valken, Steltlopers)
    VISMIG = "Vismig"    # Visuele trek (Zangvogels, Zwaluwen, Sterns, Eenden)


class Guild(Enum):
    WATERFOWL = ("Watervogels (Ganzen/Grondeleenden)", False, FlightStrategy.VISMIG)
    COASTAL_BIRDS = ("Kustvogels (Zee-eenden/Duikers/Futen)", False, FlightStrategy.VISMIG)
    RAPTORS_THERMAL = ("Roofvogels (Zwevers)", False, FlightStrategy.THERMAL)
    RAPTORS_ACTIVE = ("Roofvogels (Actief)", False, FlightStrategy.ACTIVE)
    HERONS = ("Reigers", False, FlightStrategy.ACTIVE)
    STORKS = ("Ooievaars (Zwevers)", False, FlightStrategy.THERMAL)
    SHOREBIRDS = ("Steltlopers", False, FlightStrategy.ACTIVE)
    GULLS_TERNS = ("Meeuwen & Sterns", False, FlightStrategy.VISMIG)
    PELAGICS = ("Zeevogels (Pelagics)", False, FlightStrategy.VISMIG)
    LANDBIRDS_SPECIAL = ("Speciale Landvogels", True, FlightStrategy.VISMIG)
    LANDBIRDS_REG = ("Landvogels", False, FlightStrategy.VISMIG)
    PASSERINES = ("Zangvogels", False, FlightStrategy.VISMIG)
    UNCLASSIFIED_BIRDS = ("Overige Vogels", False, FlightStrategy.VISMIG)
    OTHER = ("Niet-vogels", False, FlightStrategy.VISMIG)

    def __init__(self, display_name: str, is_special: bool, strategy: FlightStrategy):
        self.display_name = display_name
        self.is_special = is_special
        self.strategy = strategy


class SpeciesGuildMapper:
    @staticmethod
    def get_guild_by_latin(latin_name: Optional[str]) -> Guild:
        if not latin_name or not latin_name.strip():
            return Guild.UNCLASSIFIED_BIRDS

        genus = latin_name.strip().split()[0]

        if genus in {
            "Anser", "Branta", "Cygnus", "Anas", "Spatula", "Mareca", "Netta", "Aythya",
            "Tadorna", "Aix", "Alopochen", "Oxyura", "Phalacrocorax", "Microcarbo",
            "Podiceps", "Tachybaptus"
        }:
            return Guild.WATERFOWL

        if genus in {
            "Somateria", "Melanitta", "Clangula", "Bucephala", "Mergellus", "Mergus",
            "Polysticta", "Histrionicus", "Gavia"
        }:
            return Guild.COASTAL_BIRDS

        if genus in {
            "Buteo", "Pernis", "Aquila", "Hieraaetus", "Clanga", "Haliaeetus", "Milvus",
            "Gyps", "Gypaetus", "Neophron", "Aegypius", "Circaetus", "Pandion"
        }:
            return Guild.RAPTORS_THERMAL

        if genus in {"Circus", "Accipiter", "Falco", "Elanus"}:
            return Guild.RAPTORS_ACTIVE

        if genus in {
            "Ardea", "Egretta", "Bubulcus", "Ardeola", "Nycticorax", "Ixobrychus",
            "Botaurus", "Platalea", "Plegadis", "Threskiornis"
        }:
            return Guild.HERONS

        if genus in {"Ciconia"}:
            return Guild.STORKS

        if genus in {
            "Haematopus", "Himantopus", "Recurvirostra", "Burhinus", "Cursorius",
            "Glareola", "Vanellus", "Pluvialis", "Charadrius", "Numenius", "Limosa",
            "Arenaria", "Calidris", "Scolopax", "Gallinago", "Lymnocryptes",
            "Phalaropus", "Actitis", "Tringa", "Gallinula", "Fulica", "Grus",
            "Porzana", "Zapornia", "Crex", "Rallus"
        }:
            return Guild.SHOREBIRDS

        if genus in {
            "Rissa", "Pagophila", "Xema", "Chroicocephalus", "Larus", "Ichthyaetus",
            "Hydrocoloeus", "Gelochelidon", "Hydroprogne", "Thalasseus", "Sterna",
            "Sternula", "Chlidonias", "Onychoprion"
        }:
            return Guild.GULLS_TERNS

        if genus in {
            "Fulmarus", "Puffinus", "Calonectris", "Hydrobates", "Oceanodroma",
            "Morus", "Stercorarius", "Uria", "Alca", "Fratercula", "Ardenna"
        }:
            return Guild.PELAGICS

        if genus in {
            "Merops", "Upupa", "Coracias", "Alcedo", "Cuculus", "Caprimulgus",
            "Jynx", "Dendrocopos", "Dryocopus", "Picus", "Oriolus", "Lanius",
            "Picoides", "Dryobates"
        }:
            return Guild.LANDBIRDS_SPECIAL

        if genus in {
            "Columba", "Streptopelia", "Apus", "Hirundo", "Delichon", "Riparia",
            "Ptyonoprogne", "Cecropis"
        }:
            return Guild.LANDBIRDS_REG

        if genus in {
            "Fringilla", "Carduelis", "Chloris", "Spinus", "Linaria", "Acanthis",
            "Loxia", "Pyrrhula", "Coccothraustes", "Serinus", "Emberiza", "Calcarius",
            "Plectrophenax", "Passer", "Anthus", "Motacilla", "Alauda", "Lullula",
            "Galerida", "Sturnus", "Pastor", "Turdus", "Luscinia", "Erithacus",
            "Phoenicurus", "Saxicola", "Oenanthe", "Muscicapa", "Ficedula", "Sylvia",
            "Curruca", "Phylloscopus", "Acrocephalus", "Iduna", "Hippolais",
            "Locustella", "Cettia", "Parus", "Cyanistes", "Periparus", "Lophophanes",
            "Poecile", "Aegithalos", "Sitta", "Certhia", "Troglodytes", "Cinclus",
            "Regulus", "Panurus", "Corvus", "Coloeus", "Pica", "Garrulus",
            "Nucifraga", "Pyrrhocorax", "Remiz", "Bombycilla", "Carpodacus"
        }:
            return Guild.PASSERINES

        return Guild.UNCLASSIFIED_BIRDS