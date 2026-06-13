# Candor

**Candor** est un langage de programmation conçu non pas pour être agréable à *taper*
par un humain, mais pour être impossible à *se tromper* en l'écrivant — pensé du point
de vue d'une IA. Sa philosophie tient en un mot : **franchise**. Rien n'est implicite,
rien n'est caché, tout contrat est local et visible.

Ce dépôt est la *forge* : la première implémentation du langage. Le **design** de Candor
est entièrement original. L'**implémentation** de cette v0 est écrite en Python — c'est
le *bootstrapping* : tout langage naît dans un langage existant avant de pouvoir,
un jour, se réécrire dans lui-même.

## Les principes de Candor

1. **Zéro implicite.** Pas de coercition de types, pas de variable globale magique,
   pas de conversion silencieuse. Un nom inconnu est une erreur de compilation, pas une
   surprise à l'exécution. (Anti-hallucination.)
2. **Tout est typé, et le type est local.** Chaque `let` porte son type. Chaque fonction
   déclare ses paramètres, son type de retour et ses **effets**.
3. **Les effets sont dans la signature.** Une fonction qui écrit sur la console doit
   déclarer `uses [Console]`. Si elle ne le fait pas, Candor refuse de l'exécuter —
   *avant* de lancer le programme.
4. **Immuabilité.** Il n'existe aucune affectation. Un `let` lie une valeur une fois,
   pour toujours (proche de la forme SSA).
5. **Vérification locale.** Chaque fonction est vérifiable en la lisant seule : son
   contrat suffit.

## Exemple

```candor
fn square(n: Int) -> Int do
  give n * n
end

fn main() -> Int uses [Console] do
  let a: Int = 5
  let b: Int = square(a)
  say("5 au carre fait")
  say(b)
  give 0
end
```

## Deux moteurs d'exécution

Candor se compile en un vrai bytecode binaire exécuté par une machine virtuelle à pile
maison. Il existe aussi un interpréteur arbre (tree-walk) plus simple. La chaîne :

```
source .can ──► lexer ──► parser ──► checker ──► compiler ──► bytecode .canc ──► VM
                                                  └──────────► interpréteur (tree-walk)
```

```bash
python -m candor run     examples/hello.can       # interprète (tree-walk)
python -m candor compile examples/hello.can        # écrit examples/hello.canc (binaire)
python -m candor exec    examples/hello.canc        # exécute sur la VM bytecode
python -m candor dis     examples/hello.canc        # désassemble le bytecode
```

La VM possède sa **propre sémantique**, indépendante de Python — par exemple des `Int`
64 bits signés avec débordement défini (voir `examples/overflow.can`, où le même
programme donne un résultat différent selon le moteur).

## Lancer les tests

```bash
python -m pytest -q          # si pytest est installe
python tests/test_candor.py  # sinon, runner integre (16 tests)
```

## État (v0)

Implémenté : lexer, parser, vérificateur (types + effets + retour certain), interpréteur
arbre, **compilateur bytecode + machine virtuelle à pile** avec format binaire `.canc` et
désassembleur. Types : `Int`, `Bool`, `Text`, **listes immuables `[T]`** (littéraux
`[a, b, c]` ; `[]` typé par le contexte) et **enregistrements immuables** (`record Token
{ kind: Int, value: Int }`, construction `Token { ... }`, accès `t.kind`). Effet de
référence : `Console`. Intégrées : `say`, `len` (Text/liste), `at` (texte), et `cons` /
`head` / `tail` / `is_empty` / `get` (listes) — toutes pures sauf `say`.

## Vers le self-hosting

But final : réécrire le compilateur de Candor **en Candor**, pour couper le dernier
maillon Python. C'est un voyage en étapes, car le langage doit d'abord être assez
expressif pour exprimer un compilateur.

- [x] **Étape 1 — inspecter du texte + écrire un analyseur en Candor.** `len`/`at` + un
  évaluateur d'expressions à descente récursive (priorités, parenthèses) écrit
  entièrement en Candor : voir `examples/calc.can`. Comme le langage est immuable, on
  boucle par récursion. *C'est la preuve que Candor peut parser un langage.*
- [x] **Étape 2 — structures de données (listes).** Listes immuables `[T]` avec
  `cons`/`head`/`tail`/`is_empty`/`get`. Démonstration : `examples/lexer.can` transforme
  un texte en liste d'entiers (un vrai mini-lexer). *Candor peut désormais produire une
  liste de tokens.*
- [x] **Étape 2b — enregistrements (structs).** Types nommés à champs typés, construction
  `Token { ... }` et accès `t.kind`. Démonstration : `examples/tokens.can` est un lexer
  qui produit une `[Token]` typée. *Candor a maintenant tokens ET nœuds d'AST.*
- [ ] **Étape 3 — effet `File`.** Lire le code source depuis un fichier (sinon le source
  reste codé en dur dans le programme).
- [ ] **Étape 4 — self-hosting.** Réécrire lexer → parser → checker → compilateur en
  Candor, jusqu'à ce que `candor exec compilateur.canc` compile du Candor.
