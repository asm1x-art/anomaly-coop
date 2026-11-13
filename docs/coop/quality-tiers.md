# Ступени качества графики

Три набора визуальных модов из GRA 2.5 по объёму видеопамяти: **4 ГБ** (`low`), **6–8 ГБ** (`mid`), **10–12 ГБ**
(`high`). Основа — три профиля Mod Organizer из GRA («v_4gb Средние», «v_6gb Высокие», «v_12gb Все включено»): один
список модов в одном порядке, включены разные. Отсюда взято только то, что является картинкой: текстуры, модели,
частицы, трава. Шейдеры и погода (ScreenSpaceShaders, Atmospherics, Enhanced Shaders) — отдельная ветка `gra-shaders`,
один набор для всех; ступень добавляет к нему свои архивы и пресет настроек.

- Определение ступеней — данные в `tools/gra/tiers.py` (моды в порядке приоритета GRA, кому какой мод, что уступает).
- Сборка — `tools/gra/build_tiers.py`; чтение таблицы файлов архива — `tools/gra/db_list.py`.

## Компоненты

Ступень — это сумма компонентов. Каждый файл попадает ровно в один компонент по тому, какие ступени им пользуются,
поэтому внутри одной ступени ни один путь не лежит в двух компонентах (порядок загрузки архивов ступени не важен), а
смена ступени докачивает только разницу.

| Компонент | Ступени | Что внутри | Файлов | Размер | zstd |
|---|---|---|---|---|---|
| `gfx_all` | все | земля (Misery Terrain Textures), техника (Vehicle Textures Redux), трава и деревья (PanceRide Autumn), трава новых локаций (Gardener of the Zone) | 925 | 5,68 ГиБ | ≈1,87 ГиБ |
| `gfx_models` | все | модели и текстуры мутантов (KynesPeace Medium, AltPseudogiants, HD Lurker, Izlom), сталкеров (Fixed Vanilla Models & Textures), Burnt Fuzz | 1068 | 0,72 ГиБ | ≈0,28 ГиБ |
| `gfx_ui` | все | карты КПК высокого разрешения, экраны загрузки Viewport | 225 | 1,67 ГиБ | ≈0,33 ГиБ |
| `gfx_low` | 4 ГБ | текстуры мира ATO 2K на тех путях, где у 6–8 ГБ стоят ZTR и «Штрих» | 279 | 0,81 ГиБ | ≈0,27 ГиБ |
| `gfx_low_mid` | 4 и 6–8 ГБ | остальные текстуры мира ATO 2K | 353 | 0,92 ГиБ | ≈0,36 ГиБ |
| `gfx_mid_high` | 6–8 и 10–12 ГБ | Zone Textures Rework, «Штрих от Шабаша», частицы Cinematic VFX (`particles.xr` + текстуры) | 1171 | 3,26 ГиБ | ≈1,92 ГиБ |
| `gfx_high` | 10–12 ГБ | A.D.E.G.A. (4K, часть 8K) | 3660 | 8,99 ГиБ | ≈4,85 ГиБ |

| Ступень | Компоненты | Размер на диске | Скачивание (zstd) |
|---|---|---|---|
| 4 ГБ (`low`) | `gfx_all` + `gfx_models` + `gfx_ui` + `gfx_low` + `gfx_low_mid` | 9,80 ГиБ | ≈3,1 ГиБ |
| 6–8 ГБ (`mid`) | `gfx_all` + `gfx_models` + `gfx_ui` + `gfx_low_mid` + `gfx_mid_high` | 12,26 ГиБ | ≈4,8 ГиБ |
| 10–12 ГБ (`high`) | `gfx_all` + `gfx_models` + `gfx_ui` + `gfx_mid_high` + `gfx_high` | 20,33 ГиБ | ≈9,3 ГиБ |

Все семь компонентов на сервере обновлений: 22,05 ГиБ, после zstd ≈9,9 ГиБ (оценка: уровень 19, окно 2^25, куски по
32 МиБ, сжат каждый 4-й кусок). Переход 4 ГБ → 6–8 ГБ докачивает `gfx_mid_high` и убирает `gfx_low`; 6–8 → 10–12
докачивает `gfx_high` и убирает `gfx_low_mid`.

Разрешения текстур (сторона, ГиБ): `gfx_high` — 8K 0,75, 4K 4,43, 2K 3,22; `gfx_mid_high` — 8K 0,49 («Штрих»), 4K 1,38,
2K 1,32; `gfx_low` и `gfx_low_mid` — только 2K; `gfx_all` — 8K 0,65 (бампы травы PanceRide), 4K 3,82, 2K 1,14.
Занятая видеопамять не измерялась: классы 4 / 6–8 / 10–12 ГБ — это классы профилей GRA.

## Чем ступени отличаются от профилей GRA

| | GRA 4 ГБ | GRA 6 ГБ | GRA 12 ГБ | У нас |
|---|---|---|---|---|
| Текстуры мира | ATO 2K | ATO 2K + ZTR + «Штрих» | A.D.E.G.A. + ZTR + «Штрих» | так же |
| Земля, техника | Misery Terrain, Vehicle Redux | так же | так же | так же, всем |
| Трава и деревья | PanceRide Autumn | ConsciousnessGrassTrees | ConsciousnessGrassTrees | PanceRide Autumn всем |
| Частицы | ванильные | Cinematic VFX | Cinematic VFX | так же |
| Мутанты | HighResMutantsV (текстуры) | KynesPeace Medium, AltPseudogiants | S2 + KynesPeace Heavy, AltPseudogiants | KynesPeace Medium + AltPseudogiants всем |
| HD Lurker, Izlom, Fixed Vanilla Models, Burnt Fuzz, карты КПК, экраны загрузки | да | да | да | да, всем |

### Трава: одна для всех

Трава прячет от взгляда ИИ (`src/xrGame/grass_occlusion.cpp`): движок читает `level.details` локации — плотность
травы в каждом слоте 2×2 м, высоту слоя и флаг «не колышется» у моделей — и ослабляет зрение NPC вдоль луча. Читается
файл той машины, которая считает NPC, а локацию в коопе ведёт один из игроков (`is_authority`), пустую — хост. Значит,
`level.details` обязан быть одинаковым у всех, иначе заметность в траве зависит от того, кто сейчас ведёт локацию.
От консольных настроек травы (`r__detail_density`, `r__detail_radius`, высота) и от текстур расчёт не зависит: их
можно ставить пресетом ступени.

Проверено по файлам (слоты `level.details`, плотность считалась так же, как в движке):

| Локация | Ванильная | PanceRide | ConsciousnessGrassTrees |
|---|---|---|---|
| Кордон | 47,0 % слотов с травой, средняя плотность 0,235 | слоты байт в байт ванильные | 48,0 %, 0,223; отличается 46 % слотов |
| Болота | 34,0 %, 0,035 | слоты байт в байт ванильные | 45,6 %, 0,162; отличается 46 % слотов |
| Янтарь | 84,5 %, 0,233 | своего `level.details` нет (ванильный) | 89,8 %, 0,313; отличается 85 % слотов |

PanceRide меняет только модели и атлас травы (`build_details.dds`, свой `level.details` лишь у Кордона и Болот, со
слотами ванили): зрение ИИ остаётся таким же, как сейчас, хосту ничего не нужно. ConsciousnessGrassTrees переписывает
слоты на 21 локации. Поэтому по ступеням трава не различается; взята PanceRide. ConsciousnessGrassTrees возможна только
сразу всем игрокам и хосту (её `level.details`, 110 МБ, тогда должны уйти в базовый релиз) и меняет скрытность в траве
— это решение по балансу, не по графике.

Копии локаций рейда (`raid_*`) несут свои `level.details` и `build_details.dds` россыпью в релизе, россыпь сильнее
архивов: на них трава остаётся ванильной.

### Модели: один набор для всех

Сравнение OGF модов с тем, что уже в игре (кости и родители, формы костей, суставы, привязка, масса — чанки
`OGF_S_BONE_NAMES` и `OGF_S_IKDATA`):

| Мод | Скелет | Формы костей (попадания) | Суставы, привязка, масса |
|---|---|---|---|
| KynesPeace Medium (112 моделей) | совпадает у всех | отличаются у 9 моделей (кровосос — 1 кость, `dog_build_dead`, `dog_header_dead`, `afro_cat_1`) | отличаются у всех |
| KynesPeace Heavy (73) | совпадает | отличаются у 9 | отличаются у всех |
| S2 Heavy (48) | у трёх фантомов другой скелет | отличаются у кабана, химеры, плоти (до 60 костей) | отличаются; ещё свои конфиги существ и шейдеры |
| AltPseudogiants (6), HD Lurker (3), Burnt Fuzz (2) | совпадает | совпадают | привязка и масса отличаются |
| Fixed Vanilla Models (584 модели сталкеров вне пака Dux) | совпадает | у 66 отличаются 2–13 костей, 18 совпадают полностью | отличаются почти у всех |

Ни один набор не совпадает с ванильным полностью, а Heavy и Medium — между собой, поэтому модели не различаются по
ступеням: один набор всем (`gfx_models`), сборщик прерывается, если модель или `level.details` оказались бы разными у
ступеней. Имена и порядок костей у выбранных модов ванильные, так что номера костей в попаданиях сходятся и с хостом
без этих моделей; формы костей и тряпичная физика у хоста будут ванильными. Надёжнее положить `gfx_models` и хосту
(или перенести его в базовый релиз).

### Частицы

Cinematic VFX — один `particles.xr` вместо ванильного (2567 групп и 668 эффектов против 1602 и 623). Из ванильных имён
в нём нет 15 (`hit_fx\effects\hit_blood_*`, `hit_fx\effects\hit_wood_01*`, `zones_mine\zone_acidic_hit` и др.): ни
конфиги, ни скрипты, ни `gamemtl.xr` на них не ссылаются. Частицы только рисуются, в сеть не идут: разные библиотеки у
игроков безопасны. Свои `.pe/.pg` россыпью (`gamedata/particles/coop/`) сильнее библиотеки и работают с обеими. Конфиг
патронов из мода (`weapon_ammo.ltx`: трассеры, урон) не взят.

## Что не взято

| Мод GRA | Почему |
|---|---|
| ConsciousnessGrassTrees 0.71 | меняет `level.details` (см. выше) |
| Мутанты S2 (Heavy), KynesPeace (Heavy), HighResMutantsV | один набор моделей для всех — KynesPeace Medium; S2 требует конфигов существ |
| Expanded_Fixed_Maps_AIO | геометрия локаций |
| Arrival | аномалии: геймплей |
| Painter of the Zone, Следы, Расчленение | скрипты, предметы |
| Swm_Visible_Body | скрипты, тело актора |
| Persistent Weather | погоду мира ведёт хост |
| ScreenSpaceShaders, Atmospherics, Enhanced Shaders, LUT | ветка `gra-shaders` |

Из взятых модов выброшено всё, кроме текстур (`.dds`, `.thm`), моделей (`.ogf`, `.omf`), `particles.xr`,
`levels\*\level.details`, `build_details.dds/.thm` и `levels\*\terrain\*.dds`: два конфига (`weapon_ammo.ltx`,
`ui_raids_descr.xml`), рабочий мусор (`.tmp`, `.bak`, `.png`).

## Кто побеждает на одном пути

Движок регистрирует архивы по папкам в порядке `fsgame.ltx` (`db\`, `configs`, `levels`, `meshes`, `sounds`,
`textures`, `mods`, `patches`, `addons`), внутри папки — по имени; файл более позднего архива заменяет более ранний
(`CLocatorAPI::Register`), россыпь `gamedata` регистрируется последней и побеждает всё. Архивы ступеней лежат в
**`db\patches\`**: они позже `db\mods\`, поэтому сильнее ванили, `gra_*.db` и `new_levels_textures.db*` — как
ретекстуры в GRA, где они выше оружейного блока и New Levels. В `db\mods\` имя `gfx_*` шло бы раньше `gra_*` и
`new_levels_*` и проигрывало бы им.

| С чем пересекается | Путей | Кто побеждает | Как |
|---|---|---|---|
| ваниль | 5533 | ступень | `db\patches\` позже |
| `new_levels_textures.db*` | 48 | ступень (в GRA New Levels ниже ретекстур) | `db\patches\` позже |
| Dux's Character Kit, FVM Nosorog (`gra_*.db`) | 426 | наш пак (в GRA они выше Fixed Vanilla Models) | пути не пакуются (`YIELD_TO`) |
| ScreenSpaceShaders (ветка шейдеров) | 68 | шейдерная ветка | пути не пакуются (`YIELD_TO`) |
| россыпь репозитория и релиза | 2 (`textures\tile\tile_plitka_qllab_02.*`) | россыпь | пути не пакуются (`--loose`) |

В GRA над взятыми модами стоят ещё Painter of the Zone (40 текстур частиц поверх Cinematic VFX) и Swm_Visible_Body:
они не взяты, на этих путях остаются файлы взятых модов.

## Сборка

```
python tools/gra/build_tiers.py plan  [--loose <gamedata релиза вне git>] [--files список.tsv]
python tools/gra/build_tiers.py build <stage> <out> [--loose ...] [--only <компонент>] [--sample <МБ>]
```

Папка модов GRA и `converter.exe` — `--mo2`, `--converter` или переменные `GRA_MO2`, `GRA_CONVERTER`. `build` кладёт
каждый компонент в `<out>\<компонент>\db\patches\<компонент>_<вид>_NN.db` (содержимое папки компонента ложится в корень
игры; архивы до 1 ГиБ, без сжатия внутри, заголовок как у `gra_*.db`), сверяет таблицу файлов каждого архива со списком
и пишет `<out>\tiers.json` для сборщика релизов:

```json
{ "components": [{ "id": "gfx_all", "title": "…", "raw_bytes": 0, "files": 0, "mods": ["…"] }],
  "tiers": [{ "id": "low", "title": "4 ГБ", "vram_gb": [4, 5], "components": ["gfx_all", "…"] }] }
```

`--sample 40` пакует первые 40 МБ каждого компонента (проверка конвейера, в `tiers.json` пометка `"sample": true`).

## Моды и авторы

Все моды взяты из сборки GRA 2.5 как есть, без правок файлов. Авторы — как названы в файлах самих модов; где автор там
не назван, стоит название архива.

| Мод (папка в GRA) | Источник, автор | Куда |
|---|---|---|
| Misery Terrain Textures 2.8 | MBTT 2.8, moddb.com/mods/stalker-anomaly/addons/misery-based-terrain-textures-mbtt-v-10 | `gfx_all` |
| Vehicle_Textures_Redux v1.3.1 | Vehicle Textures Redux V1.3.1 (ModDB) | `gfx_all` |
| PanceRide_Autumn_Opt | Grass And Trees by PanceRide — Autumn Edition Optimized | `gfx_all` |
| Gardener of the Zone | GoTZ 6.2, moddb.com/mods/stalker-anomaly/addons/gardener-of-the-zone | `gfx_all` |
| Мутанты KynesPeace (Medium) | KynesPeace | `gfx_models` |
| AltPseudogiants | Alternative Pseudogiants | `gfx_models` |
| HD_Lurker | HD Lurker | `gfx_models` |
| Izlom YuriVernadsky | Izlom retexture V2.0, YuriVernadsky | `gfx_models` |
| Fixed_Vanilla_ModelsTextures (Light) | Fixed Vanilla Models & Textures (FVM); в readme благодарности Argus, Dynamic, nestantart | `gfx_models` |
| for Burnt Fuzz | BTTR — FIX for Burnt Fuzz | `gfx_models` |
| High_Resolution_PDA_Maps | High Resolution PDA Maps | `gfx_ui` |
| Viewport_Loading_Screens | Viewport Loading Screens | `gfx_ui` |
| Optimized_Overhual_ATO 2к (Light) | GTR optimize 2.0 (в GRA названо ATO 2K) | `gfx_low`, `gfx_low_mid` |
| DiolatorZoneTextures | Zone Textures Rework (ZTR) 1.2, 0scoar, 2025; лицензия CC BY-NC-SA 4.0 (LICENSE.md мода) | `gfx_mid_high` |
| Штрих от Шабаша | Шабаш (GRA): подборка из ATO, RE:PACK и других ретекстур, «все регалии принадлежат авторам ретекстуров»; moddb.com/mods/stalker-anomaly/addons/better-textures-for-new-old-anomaly-maps | `gfx_mid_high` |
| Cinem VFX 3.7 | Cinematic VFX 3.7 | `gfx_mid_high` |
| Adega full retexture | A.D.E.G.A. 1.5.3 | `gfx_high` |

ZTR распространяется по CC BY-NC-SA 4.0: с указанием автора, без коммерческого использования. Остальные моды лицензий
в своих файлах не несут; сборка некоммерческая, для своей группы.
