"""Conservative terminal read admission for parallel scheduling.

Not command approval: unknown commands still execute via the normal sequential
approval path. Rejecting acceleration must never mean rejecting legitimate work.
"""
import re
import shlex

_SIMPLE = frozenset({
    'cat','grep','ls','dir','head','tail','wc','stat','file','pwd','echo',
    'which','type','whereis','whoami','uname','printenv','id','groups',
    'df','du','free','uptime','ps','tasklist','nproc','lscpu','diff','cmp',
    'md5sum','sha1sum','sha256sum','sha512sum','cksum','cut','column','nl',
    'rev','strings','tr','readlink','realpath','basename','dirname','seq',
    'tac','od','expr','test','true','false',
})
_GIT_READ = frozenset({'status','log','diff','show','rev-parse','ls-files',
                       'ls-tree','blame','cat-file','shortlog','describe'})


def _stage(stage: str) -> bool:
    try:
        tokens = shlex.split(stage, posix=True)
    except ValueError:
        return False
    if not tokens:
        return False
    first, args = tokens[0], tokens[1:]
    # Assignments / env wrappers can change later shared shell state or hide a
    # command. Even assignment-only invocations must be barriers.
    if first not in _SIMPLE and first not in {
        'git','rg','sed','curl','python','python3','py','node','npm','pip','pip3','uv',
        'date','hostname','printf','sort','uniq','jq',
    }:
        return False
    if first in {'python','python3','py','node','npm','pip','pip3','uv'}:
        return len(args) == 1 and args[0] in {'--version','-V','--help'}
    if first == 'date':
        return all(a.startswith('+') or a in {'-u','--utc','--iso-8601','--version'} for a in args)
    if first == 'hostname':
        return not args or args in (['--version'],['-f'],['-s'],['-I'])
    if first == 'printf':
        return bool(args) and args[0] != '-v'
    if first == 'sed':
        # Only a numeric print-address expression, never arbitrary sed code,
        # w/e commands, script files, or substitution flags.
        return (len(args) >= 2 and args[0] == '-n'
                and re.fullmatch(r'\d+(?:,\d+)?p', args[1]) is not None
                and all(not a.startswith('-') for a in args[2:]))
    if first == 'sort':
        return not any(a.startswith(('-o','--output','--compress-program','-T','--temporary-directory')) for a in args)
    if first == 'uniq':
        # A second operand is an output filename. Ambiguous arg-taking flags
        # stay sequential; ordinary -c/-d/-u plus one input remain concurrent.
        return (all(a in {'-c','-d','-u','-i'} for a in args if a.startswith('-'))
                and len([a for a in args if not a.startswith('-')]) <= 1)
    if first == 'jq':
        # jq --run-tests has file effects; module loading can execute custom
        # behavior. Ordinary filters have no write primitive.
        return not any(a.startswith(('--run-tests','-L','--library-path')) for a in args)
    if first == 'rg':
        return not any(a.startswith(('--pre','--hostname-bin')) for a in args)
    if first == 'git':
        if any('$' in a or '`' in a for a in args):
            return False
        i = 0
        while i < len(args) and args[i].startswith('-'):
            if args[i] in {'-C','--git-dir','--work-tree'} and i+1 < len(args):
                i += 2
            elif args[i] in {'--no-pager','--literal-pathspecs'}:
                i += 1
            else:
                return False
        if i >= len(args):
            return False
        sub, rest = args[i], args[i+1:]
        if any(a.startswith(('--output','--ext-diff','--textconv','--exec')) for a in rest):
            return False
        if sub in _GIT_READ:
            return True
        if sub == 'branch':
            return not rest or all(a in {'-a','-r','-v','-vv','--list','--all','--remotes'} for a in rest)
        if sub == 'remote':
            return not rest or rest == ['-v']
        if sub == 'config':
            return bool(rest) and rest[0] in {'--get','--get-all','--get-regexp','--list','-l'}
        return False
    if first == 'curl':
        # Explicit bounded read-only HTTP syntax. No default-writing wget,
        # curl config, output files, trace files, upload or arbitrary method.
        takes_value = {'-m','--max-time','--connect-timeout','-H','--header'}
        no_value = {'--silent','--show-error','--fail','--head','--location','--compressed','--disable'}
        i = 0
        while i < len(args):
            a = args[i]
            if '$' in a or '`' in a:
                return False
            if a in takes_value:
                i += 2
                if i > len(args):
                    return False
                continue
            if a in no_value or re.fullmatch(r'-[qsfSILk]+', a):
                i += 1
                continue
            if not a.startswith(('http://','https://')):
                return False
            i += 1
        return bool(args)
    return True


def readonly(command: str) -> bool:
    if not isinstance(command, str) or not command.strip():
        return False
    # Shell syntax with hidden processes, writable redirections or parameter
    # assignment is not eligible. Plain $NAME/path args remain supported.
    if any(s in command for s in ('`','$(', '>','<','${!','${=')):
        return False
    if re.search(r'\$\{[^}]*[^\w}][^}]*\}', command):
        return False
    if re.search(r'(?<!&)&(?!&)', command):
        return False
    segments = re.split(r'\s*(?:;|&&|\|\||\|)\s*|\n', command)
    return bool(segments) and all(_stage(s.strip()) for s in segments)
