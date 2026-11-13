"""nxnativeios: the game IPA, put together on the phone. Replaces nxnative's dm/ios/tools/build_ipa.sh (xcodegen + xcodebuild + pack_ipa.py).

Inputs are build_ipa.sh's (the NSP script passes them in the environment, see build_ipa_from_nsp.py "ipa_env"), plus the player shell:
  GAME PATCHED ROMFS MSL_IOS GFXAPI AOC CONTROL DM_DISPLAY_NAME DM_BUNDLE_ID DM_APP_VERSION DM_LANG DM_SHOW_FPS DM_ICON DM_COPY_ROMFS DM_ENV_FILE
  NXB_SHELL   the unpacked shell app (Payload/DmIOS.app from shell-<title ID>.zip, release "shells")
Only single-program games (no PROGRAMS_TSV) in version 1.

The app gets: NXGame.framework (mkgameframework.py) in place of the embedded modules; dm/ the rewriter and shader tables and launcher.json, as
build_ipa.sh program_tables; romfs.img (or romfs/) with html/ and jit/ beside it, as stage_resources.sh; msl/b-<chain>[.img] (MSL source: patch 0002);
aoc/; Info.plist keys as project.yml sets them; the icon as PNG files (no asset catalog compiler on the phone).
"""
import os, plistlib, shutil, subprocess, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent / 'tools')]   # mkgameframework.py: beside this file in the app, tools/ in the repository


class AssembleError(Exception): pass


def _say(log, s): (log or print)(s)


def _repo():
    return Path(os.environ.get('NXB_UPSTREAM') or HERE.parent / 'upstream').resolve()


def _game_py(repo, *args):
    r = subprocess.run([sys.executable, str(repo / 'dm/games/game.py'), *args], capture_output=True, text=True)
    if r.returncode: raise AssembleError(f'game.py {" ".join(args)}: {r.stdout.strip()[-300:]}')
    return r.stdout.strip()


def _copy(src, dst):
    src, dst = Path(src), Path(dst)
    if dst.exists() or dst.is_symlink(): shutil.rmtree(dst) if dst.is_dir() and not dst.is_symlink() else dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir(): shutil.copytree(src, dst)
    else:
        try: os.link(src, dst)   # same volume: no second copy of a multi-GB file
        except OSError: shutil.copyfile(src, dst)


def tables(repo, game, patched, gfx, td, control, log=None):
    """build_ipa.sh program_tables: the rewriter's tables, the shader tables and the launcher's settings into td"""
    gd = Path(_game_py(repo, 'dir', game))
    td.mkdir(parents=True, exist_ok=True)
    for pat in ('*.fixups.tsv', '*.gates.tsv', '*.cuts.tsv', '*.obs.tsv'):
        found = list(Path(patched).glob(pat))
        if not found: raise AssembleError(f'no rewriter tables {pat} in {patched}')
        for f in found: shutil.copyfile(f, td / f.name)
    if (Path(patched) / 'nro.tsv').is_file(): shutil.copyfile(Path(patched) / 'nro.tsv', td / 'nro.tsv')
    need = ['shader_map.tsv', 'pso_manifest.tsv'] + ([] if gfx in ('vulkan', 'gl') else ['c1_full.tsv'])
    for f in need:
        if not (gd / f).is_file(): raise AssembleError(f'missing {gd / f}')
        shutil.copyfile(gd / f, td / f)
    if gfx not in ('vulkan', 'gl'):
        for f in ('cb_extent.tsv', 'shader_pairs.tsv', 'pso_pairs.tsv'):
            if (gd / f).is_file(): shutil.copyfile(gd / f, td / f)
    env = dict(os.environ, GFXAPI=gfx)
    r = subprocess.run([sys.executable, str(repo / 'dm/games/settings.py'), game, str(patched), str(control or ''), str(td / 'launcher.json')], capture_output=True, text=True, env=env)
    if r.returncode: raise AssembleError(f'launcher settings (settings.py): {r.stdout.strip()[-300:]}')
    _say(log, f'launcher: {r.stdout.strip()}')


def chain_version(repo):
    for line in (repo / 'dm/gfx/nvn/dmsh_chain.h').read_text().splitlines():
        if line.startswith('#define DMSH_CHAIN "'): return line.split('"')[1]
    raise AssembleError('no DMSH_CHAIN in dmsh_chain.h')


def _app_icon(icon, app, log):
    """The app's own nxb_icon_png (ImageIO) writes the 120 and 180 px PNGs from the game's JPEG: no Pillow on the phone"""
    try:
        import ctypes
        f = ctypes.CDLL(None).nxb_icon_png; f.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        ok = all(f(str(icon).encode(), str(app / n).encode(), px) == 0 for px, n in ((120, 'NXIcon60x60@2x.png'), (180, 'NXIcon60x60@3x.png')))
        if ok: _say(log, f'app icon: the game\'s own ({Path(icon).name})')
        return ok
    except (AttributeError, OSError): return False


def icon_pngs(icon, app, log=None):
    """The game icon as PNG files named in CFBundleIcons (the shell has no compiled asset catalog for it). UIKit scales the 120 / 180 px files."""
    try:
        from PIL import Image   # optional; the app passes a PNG it made with UIKit instead (NXB_ICON_PNG)
    except ImportError: Image = None
    names = []
    png = os.environ.get('NXB_ICON_PNG')
    if png and Path(png).is_file():
        shutil.copyfile(png, app / 'NXIcon60x60@3x.png'); names = ['NXIcon60x60']
    elif Image and icon and Path(icon).is_file():
        im = Image.open(icon).convert('RGB')
        for px, n in ((120, 'NXIcon60x60@2x.png'), (180, 'NXIcon60x60@3x.png')): im.resize((px, px)).save(app / n)
        names = ['NXIcon60x60']
    elif icon and Path(icon).is_file() and _app_icon(icon, app, log): names = ['NXIcon60x60']
    else: _say(log, 'no icon PNG: the home-screen icon will be blank')
    return names


def assemble(out_ipa, log=None):
    e = os.environ; repo = _repo()
    if e.get('PROGRAMS_TSV'): raise AssembleError('games of several programs are not supported on the phone yet')
    game, patched, romfs, msl_ios = e['GAME'], Path(e['PATCHED']), Path(e['ROMFS']), Path(e['MSL_IOS'])
    gfx = e.get('GFXAPI') or 'nvn'
    if e.get('NXB_SHELL') and e['NXB_SHELL'] != 'None': shell = Path(e['NXB_SHELL'])
    else:   # the bundled shell for this game: shell-<title ID>.zip (release "shells"), unpacked once per build
        z = Path(e.get('NXB_SHELLS', '')) / f'shell-{game.upper()}.zip'
        if not z.is_file(): raise AssembleError(f'no player shell for {game} ({z.name}): add the title ID to the "Player shells" workflow and rebuild the app')
        dst = Path(e.get('W') or out_ipa.parent / 'ipa-work') / 'shell'; shutil.rmtree(dst, ignore_errors=True)
        with zipfile.ZipFile(z) as zf: zf.extractall(dst)
        apps = list((dst / 'Payload').glob('*.app'))
        if len(apps) != 1: raise AssembleError(f'{z.name} holds no app')
        shell = apps[0]
        for f in shell.rglob('*'):   # zipfile does not keep the executable bit
            if f.is_file() and f.name in ('DmIOS',): f.chmod(0o755)
    info_shell = shell / 'nxshell.json'
    if info_shell.is_file():
        import json; meta = json.loads(info_shell.read_text())
        if meta.get('game') != game: raise AssembleError(f'the player shell is for {meta.get("game")}, not {game}')
    work = Path(e.get('W') or out_ipa.parent / 'ipa-work'); stage = work / 'Payload'
    if stage.exists(): shutil.rmtree(stage)
    app = stage / shell.name
    _say(log, f'app: {e.get("DM_DISPLAY_NAME")} {e.get("DM_APP_VERSION")} ({e.get("DM_BUNDLE_ID")})')
    shutil.copytree(shell, app, symlinks=True)
    # the game's code: NXGame.framework
    mods = _game_py(repo, 'modules', game, str(patched)).split()
    jit = romfs.parent / 'jit/jit.img'
    import mkgameframework as mk
    fw = app / 'Frameworks/NXGame.framework'; fw.mkdir(parents=True, exist_ok=True)
    _say(log, f'NXGame.framework: {" ".join(mods)}')
    mk.write_dylib(mk.layout_sections(str(patched), mods, '', str(jit) if jit.is_file() else None), str(fw / 'NXGame'), 'ios')
    (fw / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': f'{e["DM_BUNDLE_ID"]}.NXGame', 'CFBundleExecutable': 'NXGame', 'CFBundlePackageType': 'FMWK',
        'CFBundleName': 'NXGame', 'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0', 'MinimumOSVersion': '26.0', 'CFBundleSupportedPlatforms': ['iPhoneOS']}))
    # tables
    tables(repo, game, patched, gfx, app / 'dm', e.get('CONTROL') or romfs.parent / 'control.nacp', log)
    # the game files (stage_resources.sh sync_romfs / beside_romfs)
    if e.get('DM_COPY_ROMFS', 'YES') == 'NO':   # the game files stay out: the identity of the image goes in, so the app only takes the image this build was made for
        if romfs.is_file():
            sys.path.insert(0, str(repo / 'dm/tools')); import romfs_image
            (app / 'romfs.id').write_text(romfs_image.identity(str(romfs), game, e.get('DM_APP_VERSION') or '1.0', e.get('PKG', '')) + '\n')
        _say(log, 'game files: left out of the IPA; copy romfs.img into the game\'s folder in Files')
    if e.get('DM_COPY_ROMFS', 'YES') != 'NO':
        _copy(romfs, app / ('romfs.img' if romfs.is_file() else 'romfs'))
        _say(log, f'game files: {romfs.name}')
    for d in ('html', 'jit'):
        if (romfs.parent / d).is_dir(): _copy(romfs.parent / d, app / d)
    # shaders
    msldir = {'vulkan': 'vk', 'gl': 'gl'}.get(gfx, 'b-' + chain_version(repo))
    src = msl_ios / msldir
    if src.is_dir(): _copy(src, app / 'msl' / msldir)
    elif Path(str(src) + '.img').is_file(): _copy(Path(str(src) + '.img'), app / 'msl' / (msldir + '.img'))
    else: raise AssembleError(f'no shader libraries at {src}')
    # DLC
    if e.get('AOC') and Path(e['AOC']).is_dir(): _copy(e['AOC'], app / 'aoc')
    if e.get('DM_ENV_FILE') and Path(e['DM_ENV_FILE']).is_file(): shutil.copyfile(e['DM_ENV_FILE'], app / 'dm/env.txt')
    # Info.plist, as project.yml / build_ipa.sh set it
    ip = app / 'Info.plist'; info = plistlib.loads(ip.read_bytes())
    info.update(CFBundleIdentifier=e['DM_BUNDLE_ID'], CFBundleDisplayName=e.get('DM_DISPLAY_NAME') or game, CFBundleName=(e.get('DM_DISPLAY_NAME') or game)[:15],
                CFBundleShortVersionString=e.get('DM_APP_VERSION') or '1.0', CFBundleVersion=e.get('DM_APP_VERSION') or '1.0',
                DMShowFPS=e.get('DM_SHOW_FPS', '1') in ('1', 'YES'), DMLanguage=e.get('DM_LANG') or 'en-US')
    if gfx not in ('vulkan', 'gl'): info['DMChain'] = msldir[2:]
    names = icon_pngs(e.get('DM_ICON'), app, log)
    if names: info['CFBundleIcons'] = {'CFBundlePrimaryIcon': {'CFBundleIconFiles': names, 'CFBundleIconName': names[0]}}
    ip.write_bytes(plistlib.dumps(info))
    sizes = sorted(((sum(f.stat().st_size for f in q.rglob('*') if f.is_file()) if q.is_dir() else q.stat().st_size, q.name) for q in app.iterdir()), reverse=True)
    _say(log, 'IPA contents: ' + ', '.join(f'{n} {b / 1e9:.1f} GB' for b, n in sizes[:5] if b > 5e7))
    sign_stage(work, log)
    pack(stage, out_ipa, log)
    shutil.rmtree(stage, ignore_errors=True)
    return out_ipa


def sign_stage(work, log):
    """The user's own .p12 and profile (Settings → Signing) sign the app in place, before it is zipped: no second copy of the game, and the IPA comes out ready to install.
    The signer is zsign, built into the app (nxb_sign_app, ZSign/nxb_sign.cpp)"""
    p12, prov = os.environ.get('NXB_SIGN_P12'), os.environ.get('NXB_SIGN_PROFILE')
    if not (p12 and prov and os.path.isfile(p12) and os.path.isfile(prov)): return False
    import ctypes, plistlib
    raw = Path(prov).read_bytes(); a, b = raw.find(b'<?xml'), raw.rfind(b'</plist>')
    appid = (plistlib.loads(raw[a:b + 8]).get('Entitlements') or {}).get('application-identifier', '') if a >= 0 and b > a else ''
    bid = appid.partition('.')[2]
    bid = '' if bid in ('', '*') or bid.endswith('*') else bid   # an explicit app ID in the profile is the bundle ID the app must have; a wildcard keeps the game's own
    try: fn = ctypes.CDLL(None).nxb_sign_app
    except AttributeError: raise AssembleError('this build of the app has no signer: update the app')
    fn.argtypes = [ctypes.c_char_p] * 5 + [ctypes.c_char_p, ctypes.c_int]
    err = ctypes.create_string_buffer(500)
    _say(log, f'signing with your certificate{" as " + bid if bid else ""} ...')
    rc = fn(str(work).encode(), p12.encode(), os.environ.get('NXB_SIGN_PW', '').encode(), prov.encode(), bid.encode(), err, 500)
    if rc: raise AssembleError(f'signing failed: {err.value.decode() or rc}')
    _say(log, 'signed: the IPA is ready to install')
    return True


def pack(stage, out_ipa, log=None):
    """Payload/ → the IPA. Large files are stored (the game files and shader images do not compress much, and the phone would take hours), small ones deflated."""
    out_ipa = Path(out_ipa); tmp = out_ipa.with_suffix('.ipa.part')
    files = sorted(p for p in stage.rglob('*') if p.is_file() or p.is_symlink())
    total = sum(p.stat().st_size for p in files if p.is_file()); done = 0; last = -1
    with zipfile.ZipFile(tmp, 'w', allowZip64=True) as z:
        for p in files:
            arc = p.relative_to(stage.parent).as_posix()
            if p.is_symlink():
                zi = zipfile.ZipInfo(arc); zi.create_system = 3; zi.external_attr = (0o120777 << 16)
                z.writestr(zi, os.readlink(p)); continue
            big = p.stat().st_size > (1 << 20)
            zi = zipfile.ZipInfo.from_file(p, arc); zi.compress_type = zipfile.ZIP_STORED if big else zipfile.ZIP_DEFLATED
            with open(p, 'rb') as src, z.open(zi, 'w', force_zip64=big) as dst:
                while chunk := src.read(8 << 20):
                    dst.write(chunk); done += len(chunk)
                    pct = done * 100 // max(1, total)
                    if pct != last and pct % 5 == 0: _say(log, f'pack IPA {pct}%'); last = pct
    os.replace(tmp, out_ipa)
    _say(log, f'IPA: {out_ipa} ({out_ipa.stat().st_size / 1e9:.2f} GB)')
