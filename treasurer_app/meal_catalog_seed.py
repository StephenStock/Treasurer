# Initial rows for Affordable Catering (UK) — sourced from their menu PDF.
# Lodge Office stores these in SQLite so the Secretary can edit prices and dishes in the app.
# Tuple: (course, label, price_pence_or_none, is_vegetarian)
# price None = included in the standard per-head package; int = extra supplement in pence.

AFFORDABLE_CATERING_RAW: list[tuple[str, str, int | None, bool]] = [
    # --- Starters (included in 3-course package @ £26) ---
    (
        "starter",
        "Choice of homemade soup (e.g. tomato & basil, minestrone, leek & potato, butternut squash, "
        "mulligatawny, pea & ham, tomato & roasted red pepper, broccoli & stilton)",
        None,
        False,
    ),
    (
        "starter",
        "Paté Maison on a bed of leaves with toasted ciabatta and red onion chutney",
        None,
        False,
    ),
    ("starter", "Vegetable spring rolls with a sweet chilli drizzle", None, False),
    ("starter", "Trio of melon with red berry compote", None, False),
    ("starter", "Hot & spicy buffalo chicken wings", None, False),
    ("starter", "Prawn sundae with Marie Rose sauce", None, False),
    (
        "starter",
        "Beef and cherry tomato stack with mozzarella pearls and pesto",
        None,
        False,
    ),
    ("starter", "Whitebait with tartare sauce", None, False),
    ("starter", "Chicken Caesar salad", None, False),
    ("starter", "Deep fried mushrooms with garlic mayonnaise", None, False),
    # Starter upgrades
    (
        "starter",
        "Upgrade: deep fried Brie with red onion chutney & toasted ciabatta",
        250,
        False,
    ),
    ("starter", "Upgrade: trio of melon with Parma ham", 250, False),
    (
        "starter",
        "Upgrade: West Country crab cakes with a sweet chilli drizzle",
        250,
        False,
    ),
    (
        "starter",
        "Upgrade: sautéed wild mushrooms with crisp pancetta on garlic crostini",
        250,
        False,
    ),
    (
        "starter",
        "Upgrade: flat mushroom stuffed with spinach & ricotta with red onion chutney",
        250,
        False,
    ),
    (
        "starter",
        "Upgrade: Creole prawns with sweet chilli jam and a wedge of lime",
        250,
        False,
    ),
    (
        "starter",
        "Upgrade: baked Camembert with fig & apple chutney and rustic bread",
        350,
        False,
    ),
    (
        "starter",
        "Upgrade: prawn, smoked salmon & crevette salad",
        350,
        False,
    ),
    (
        "starter",
        "Upgrade: antipasti platter with continental meats, cheeses, olives and rustic breads",
        350,
        False,
    ),
    ("starter", "Upgrade: gnocchi with sage butter", 350, False),
    # --- Main courses (included) ---
    (
        "main",
        "Choice of homemade pie with golden shortcrust, creamy mustard mash & green beans "
        "(steak & ale, chicken & leek, steak & kidney, chicken & ham, chicken & mushroom)",
        None,
        False,
    ),
    (
        "main",
        "Roast turkey with traditional trimmings, roast potatoes, cauliflower cheese, "
        "roast parsnips, glazed carrot batons and green beans",
        None,
        False,
    ),
    (
        "main",
        "Mediterranean chicken — breast with tomato & roasted vegetable sauce, sauté potatoes & green beans",
        None,
        False,
    ),
    (
        "main",
        "Roasted shoulder of pork with stuffing & crackling, roast potatoes, braised red cabbage, "
        "roast parsnips, swede & carrot mash, cider gravy",
        None,
        False,
    ),
    (
        "main",
        "Herb crusted salmon with tomato bisque, new potatoes and green beans",
        None,
        False,
    ),
    (
        "main",
        "Tenderloin of pork stroganoff — brandy, mushroom & tarragon cream on white & wild rice",
        None,
        False,
    ),
    (
        "main",
        "Freshly beer battered cod & chips with mushy or garden peas",
        None,
        False,
    ),
    (
        "main",
        "Chicken breast in wild mushroom, white wine & cream sauce with roasted new potatoes & green beans",
        None,
        False,
    ),
    (
        "main",
        "Cumberland sausage whirl with mash, onion & red wine gravy, topped with onion rings",
        None,
        False,
    ),
    (
        "main",
        "Thai green chicken curry on jasmine rice with poppadoms",
        None,
        False,
    ),
    (
        "main",
        "Roast chicken with stuffing, roast potatoes, cauliflower & broccoli Mornay, "
        "swede & carrot mash and green beans",
        None,
        False,
    ),
    # Vegetarian mains (menu vegetarian section)
    (
        "main",
        "Roasted pepper stuffed with wild mushroom, asparagus & pea risotto, new potatoes & green beans",
        None,
        True,
    ),
    (
        "main",
        "Vegetarian sausage toad in the hole with mash, peas and gravy",
        None,
        True,
    ),
    (
        "main",
        "Mediterranean tart with new potatoes and green beans",
        None,
        True,
    ),
    (
        "main",
        "Roasted vegetable lasagne with salad and garlic bread",
        None,
        True,
    ),
    (
        "main",
        "Brie and mushroom Wellington with roasted new potatoes and green beans",
        None,
        True,
    ),
    # Main upgrades
    (
        "main",
        "Upgrade: roast rump of beef with Yorkshire pudding, roast potatoes, braised red cabbage, "
        "glazed carrots & green beans, red wine gravy",
        450,
        False,
    ),
    (
        "main",
        "Upgrade: fillets of seabass with lemon butter, new potatoes and fine green beans",
        450,
        False,
    ),
    (
        "main",
        "Upgrade: lamb shank with red wine & redcurrant jus, rosemary mash and green beans",
        450,
        False,
    ),
    (
        "main",
        "Upgrade: chicken ballotine — spinach & cream cheese, Parma ham, Anya potato & garlic cake, "
        "green beans, creamy spinach sauce",
        450,
        False,
    ),
    (
        "main",
        "Upgrade: fillet of seabream with crayfish & parsley butter, samphire, herby new potatoes",
        450,
        False,
    ),
    (
        "main",
        "Upgrade: rump of lamb (medium) with port & redcurrant reduction, Anya potato & garlic cake",
        450,
        False,
    ),
    (
        "main",
        "Upgrade: slow roasted fillet of beef with wild mushroom duxelle, puff pastry, "
        "Masala wine reduction, Dauphinoise potatoes",
        800,
        False,
    ),
    (
        "main",
        "Upgrade: loin of monkfish on lobster bisque with Dauphinoise potatoes",
        800,
        False,
    ),
    (
        "main",
        "Upgrade: rack of lamb with red wine & redcurrant reduction, Dauphinoise potatoes",
        800,
        False,
    ),
    # --- Desserts (included in package; cheesecakes etc.) ---
    ("dessert", "Sticky toffee pudding (with custard)", None, False),
    ("dessert", "Lemon sponge (with custard)", None, False),
    ("dessert", "Spotted dick (with custard)", None, False),
    ("dessert", "Treacle sponge (with custard)", None, False),
    ("dessert", "Jam roly poly (with custard)", None, False),
    ("dessert", "Bread pudding (with custard)", None, False),
    ("dessert", "Brioche & Baileys pudding (with custard)", None, False),
    ("dessert", "Apple & berry crumble (with custard)", None, False),
    ("dessert", "Lemon cheesecake (with cream)", None, False),
    ("dessert", "Chocolate brownie cheesecake (with cream)", None, False),
    ("dessert", "Honeycomb cheesecake (with cream)", None, False),
    ("dessert", "Oreo cheesecake (with cream)", None, False),
    ("dessert", "Rolo cheesecake (with cream)", None, False),
    ("dessert", "Irish cream cheesecake (with cream)", None, False),
    ("dessert", "White chocolate cheesecake (with cream)", None, False),
    ("dessert", "White chocolate & raspberry cheesecake (with cream)", None, False),
    ("dessert", "Profiteroles with chocolate ganache", None, False),
    ("dessert", "Lemon meringue pie", None, False),
    ("dessert", "Banoffee pie", None, False),
    ("dessert", "Warm chocolate brownie with ice cream", None, False),
    ("dessert", "Chocolate mousse with strawberries", None, False),
    ("dessert", "Lemon posset with shortbread", None, False),
    ("dessert", "Black Forest gateau", None, False),
    ("dessert", "Warm chocolate fudge cake with ice cream", None, False),
    ("dessert", "Cheese & biscuits", None, False),
]


def expand_seed_for_database() -> list[tuple[str, int, str, int | None, bool]]:
    """Return rows ready for INSERT: course, sort_order, label, price_pence, is_vegetarian."""
    order = {"starter": 0, "main": 0, "dessert": 0}
    out: list[tuple[str, int, str, int | None, bool]] = []
    for course, label, price, veg in AFFORDABLE_CATERING_RAW:
        so = order[course]
        order[course] = so + 1
        out.append((course, so, label, price, veg))
    return out
