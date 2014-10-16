#!./env/bin/python
"""
OpenBazaar launcher script.
Authors: Angel "gubatron" Leon
"""

import argparse
import multiprocessing
import os
import sys
import threading

import psutil

from network_util import init_aditional_STUN_servers, check_NAT_status
from openbazaar_daemon import node_starter, OpenBazaarContext
import setup_db


def arg_to_key(arg):
    """
    Convert a long-form command line switch to an uppercase equivalent
    dict key, replacing '-' with '_'.

    Example: arg_to_key('--super_flag') == 'SUPER_FLAG'
    """
    return arg.lstrip('-').upper().replace('-', '_')


def create_argument_parser():
    defaults = OpenBazaarContext.get_defaults()
    default_db_path = os.path.join(defaults['DB_DIR'], defaults['DB_FILE'])
    default_log_path = os.path.join(defaults['LOG_DIR'], defaults['LOG_FILE'])

    parser = argparse.ArgumentParser(
        description='OpenBazaar launcher script',
        usage=usage(),
        add_help=False
    )

    # Argument entries should have the mandatory long form first.
    plain_args = (
        ('--bm-pass',),
        ('--bm-user',),
        ('--config-file',),
        ('--http-ip', '-k'),
        ('--log-level',),
        ('--market-id', '-u'),
        ('--server-ip', '-i')
    )
    for switches in plain_args:
        key = arg_to_key(switches[0])
        parser.add_argument(*switches, default=defaults[key])

    int_args = (
        ('--bm-port',),
        ('--dev-nodes', '-n'),
        ('--http-port', '-q'),
        ('--server-port', '-p')
    )
    for switches in int_args:
        key = arg_to_key(switches[0])
        parser.add_argument(*switches, type=int, default=defaults[key])

    true_args = (
        ('--dev-mode', '-d'),
        ('--disable-open-browser',),
        ('--disable-sqlite-crypt',),
        ('--disable-stun-check',),
        ('--disable-upnp', '-j'),
        ('--enable-ip-checker',),
        ('--seed-mode', '-S')
    )
    for switches in true_args:
        key = arg_to_key(switches[0])
        parser.add_argument(*switches, action='store_true', default=defaults[key])

    # Add miscellaneous flags.
    parser.add_argument('-s', '--seeds', nargs='*', default=defaults['SEEDS'])
    parser.add_argument('--db-path', default=default_db_path)
    parser.add_argument('-l', '--log', default=default_log_path)

    # Add valid commands.
    parser.add_argument('command', choices=('start', 'stop'))

    return parser


def usage():
    return """
openbazaar [options] <command>

    COMMANDS
        start            Start OpenBazaar
        stop             Stop OpenBazaar

    EXAMPLES
        openbazaar start
        openbazaar --disable-upnp --seed-mode start
        openbazaar --enable-ip-checker start
        openbazaar -d --dev-nodes 4 -j --disable-stun-check start
        openbazaar --dev-mode -n 4 --disable-upnp start

    OPTIONS
    -i, --server-ip <ip address>
        Server public IP

    -p, --server-port <port number>
        Server public (P2P) port (default: 12345)

    -k, --http-ip <ip address>
        Web interface IP (default 127.0.0.1; use 0.0.0.0 for any)

    -q, --http-port <port number>
        Web interface port (-1 = random by default)

    -l, --log <file path>
        Log file path (default 'logs/production.log')

    --log-level <level>
        Log verbosity level (default: 10 - DEBUG)
        Expected <level> values are:
           0 - NOT SET
          10 - DEBUG
          20 - INFO
          30 - WARNING
          40 - ERROR
          50 - CRITICAL

    -d, --dev-mode
        Enable development mode

    -n, --dev-nodes
        Number of dev nodes to start up

    --db-path
        Database file path. (default 'db/od.db')

    --disable-sqlite-crypt
        Disable encryption on sqlite database

    --bm-user
        Bitmessage API username

    --bm-pass
        Bitmessage API password

    --bm-port
        Bitmessage API port

    -u, --market-id
        Market ID

    -j, --disable-upnp
        Disable automatic UPnP port mappings

    --disable-stun-check
        Disable automatic port setting via STUN servers (NAT Punching attempt)

    -S, --seed-mode
        Enable seed mode

    --disable-open-browser
        Don't open preferred web browser automatically on start

    --config-file
        Disk path to an OpenBazaar configuration file

    --enable-ip-checker
        Enable periodic IP address checking.
        Useful in case you expect your IP to change rapidly.
"""


def create_openbazaar_contexts(arguments, nat_status):
    """
    Returns List<OpenBazaarContext>.

    If we are on production mode, the list will contain a
    single OpenBazaarContext object based on the arguments passed.

    If a configuration file is passed, settings from the configuration
    file will be read first, and whatever other parameters have been
    passed via the command line will override the settings on the
    configuration file.
    :rtype : list of [OpenBazaarContext]
    """
    defaults = OpenBazaarContext.get_defaults()

    server_ip = defaults['SERVER_IP']
    if server_ip != arguments.server_ip:
        server_ip = arguments.server_ip
    elif nat_status is not None:
        print nat_status
        server_ip = nat_status['external_ip']

    # "I'll purposefully leave these seemingly useless Schlemiel-styled
    # comments as visual separators to denote the beginning and end of
    # these ifs statements. They're actually nice to have when maintaining
    # so many ifs blocks. Feel free to remove post merge if they truly
    # annoy you." -Gubatron :)

    # market port
    server_port = defaults['SERVER_PORT']
    if arguments.server_port != server_port:
        server_port = arguments.server_port
    elif nat_status is not None:
        # override the port for p2p communications with the one
        # obtained from the STUN server.
        server_port = nat_status['external_port']

    # log path (requires LOG_DIR to exist)
    if not os.path.exists(defaults['LOG_DIR']):
        os.makedirs(defaults['LOG_DIR'], 0755)

    log_path = os.path.join(defaults['LOG_DIR'], defaults['LOG_FILE'])
    if arguments.log is not None and arguments.log != log_path:
        log_path = arguments.log

    # db path
    if not os.path.exists(defaults['DB_DIR']):
        os.makedirs(defaults['DB_DIR'], 0755)

    db_path = os.path.join(defaults['DB_DIR'], defaults['DB_FILE'])
    if arguments.db_path != db_path:
        db_path = arguments.db_path

    ob_ctxs = []

    if not arguments.dev_mode:
        # we return a list of a single element, a production node.
        ob_ctxs.append(OpenBazaarContext(nat_status,
                                         server_ip,
                                         server_port,
                                         arguments.http_ip,
                                         arguments.http_port,
                                         db_path,
                                         log_path,
                                         arguments.log_level,
                                         arguments.market_id,
                                         arguments.bm_user,
                                         arguments.bm_pass,
                                         arguments.bm_port,
                                         arguments.seeds,
                                         arguments.seed_mode,
                                         arguments.dev_mode,
                                         arguments.dev_nodes,
                                         arguments.disable_upnp,
                                         arguments.disable_stun_check,
                                         arguments.disable_open_browser,
                                         arguments.disable_sqlite_crypt,
                                         arguments.enable_ip_checker))
    elif arguments.dev_nodes > 0:
        # create OpenBazaarContext objects for each development node.
        i = 1
        db_path = os.path.join(defaults['DB_DIR'], 'this_will_be_ignored')
        db_dirname = os.path.dirname(db_path)
        while i <= arguments.dev_nodes:
            db_dev_filename = defaults['DEV_DB_FILE'].format(i)
            db_path = os.path.join(db_dirname, db_dev_filename)
            ob_ctxs.append(OpenBazaarContext(nat_status,
                                             server_ip,
                                             server_port + i - 1,
                                             arguments.http_ip,
                                             arguments.http_port,
                                             db_path,
                                             log_path,
                                             arguments.log_level,
                                             arguments.market_id,
                                             arguments.bm_user,
                                             arguments.bm_pass,
                                             arguments.bm_port,
                                             arguments.seeds,
                                             arguments.seed_mode,
                                             arguments.dev_mode,
                                             arguments.dev_nodes,
                                             arguments.disable_upnp,
                                             arguments.disable_stun_check,
                                             arguments.disable_open_browser,
                                             arguments.disable_sqlite_crypt,
                                             arguments.enable_ip_checker))
            i += 1

    return ob_ctxs


def ensure_database_setup(ob_ctx, defaults):
    db_path = ob_ctx.db_path
    default_db_path = os.path.join(defaults['DB_DIR'], defaults['DB_FILE'])
    default_dev_db_path = os.path.join(defaults['DB_DIR'],
                                       defaults['DEV_DB_FILE'])

    if ob_ctx.dev_mode and db_path == default_db_path:
        # override default db_path to developer database path.
        db_path = default_dev_db_path

    # make sure the folder exists wherever it is
    db_dirname = os.path.dirname(db_path)
    if not os.path.exists(db_dirname):
        os.makedirs(db_dirname, 0755)

    if not os.path.exists(db_path):
        # setup the database if file not there.
        print "[openbazaar] bootstrapping database ", os.path.basename(db_path)
        setup_db.setup_db(db_path, ob_ctx.disable_sqlite_crypt)
        print "[openbazaar] database setup completed"


def start(arguments):
    defaults = OpenBazaarContext.get_defaults()
    init_aditional_STUN_servers()

    # Turn off checks that don't make sense in development mode
    if arguments.dev_mode:
        print "DEVELOPMENT MODE! (Disable STUN check and UPnP mappings)"
        arguments.disable_stun_check = True
        arguments.disable_upnp = True

    # Try to get NAT escape UDP port
    nat_status = None
    if not arguments.disable_stun_check:
        print "Checking NAT Status..."
        nat_status = check_NAT_status()
    else:
        assert arguments.server_ip, "Need public IP if not using STUN."

    ob_ctxs = create_openbazaar_contexts(arguments, nat_status)

    for ob_ctx in ob_ctxs:
        ensure_database_setup(ob_ctx, defaults)

    multiprocessing.Process(target=node_starter, args=(ob_ctxs,)).start()


def terminate_or_kill_process(process):
    try:
        process.terminate()  # in POSIX, sends SIGTERM.
        process.wait(5)
    except psutil.TimeoutExpired:
        _, alive = psutil.wait_procs([process], None, None)
        if process in alive:
            process.kill()  # sends KILL signal.


def stop():
    my_pid = os.getpid()  # don't kill the killer.
    for process in psutil.process_iter():
        try:
            pdict = process.as_dict()
            if my_pid != int(pdict['pid']) and pdict['cmdline'] is not None:
                cmd = ' '.join(pdict['cmdline'])
                if cmd.find('openbazaar') > -1 and cmd.find('start') > -1:
                    threading.Thread(
                        target=terminate_or_kill_process,
                        args=(process,)
                    ).start()
        except psutil.NoSuchProcess:
            pass


def load_config_file_arguments(parser):
    """
    Load configuration file into sys.argv for further argument parsing.
    """
    parsed_arguments = parser.parse_args()
    if parsed_arguments.config_file is not None:
        try:
            with open(parsed_arguments.config_file) as fp:
                config_file_lines = fp.readlines()
        except IOError as e:
            print "NOTICE: Ignoring invalid config file: ",
            print parsed_arguments.config_file
            print e
            return

        # in case user entered config flags
        # in multiple lines, we'll keep only
        # those that don't start with '#'
        # also ignore everything after a '#' character
        # for every line.
        valid_config_lines = []
        for line in config_file_lines:
            if line.startswith('#'):
                continue

            normalized_line = line.strip()
            if line.find('#') != -1:
                normalized_line = line[:line.find('#')]

            if len(normalized_line) > 0:
                valid_config_lines.append(normalized_line)

        # 1. join read lines list into a string,
        # 2. re-split it to make it look like sys.argv
        # 3. get rid of possible '' list elements
        # 4. merge the new arguments from the file into sys.argv
        if len(valid_config_lines) > 0:
            config_file_arguments = [x for x in
                                     ' '.join(valid_config_lines).split(' ')
                                     if len(x) > 0]
            sys.argv[1:1] = config_file_arguments


def main():
    parser = create_argument_parser()
    load_config_file_arguments(parser)
    arguments = parser.parse_args()

    if arguments.command == 'start':
        start(arguments)
    elif arguments.command == 'stop':
        stop()
    else:
        print "[openbazaar] Invalid command '%s'" % arguments.command
        print "[openbazaar] Valid commands are 'start', 'stop'."


if __name__ == '__main__':
    main()
