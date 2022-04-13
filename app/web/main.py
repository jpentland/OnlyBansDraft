from quart import Quart, render_template, url_for, redirect, app, websocket
import asyncio
import asyncpg
import random
from functools import wraps
import os
import re
import tempfile
import json
from typing import Union

# Get environment variables
dbuser = os.environ.get('DBUSER', 'postgres')
dbpass = os.environ.get('DBPASS', 'postgres')
dbhost = os.environ.get('DBHOST', 'localhost')
dbport = os.environ.get('DBPORT', '5432')
dbname = os.environ.get('DBNAME', 'onlybans')

# Start quart application
app = Quart(__name__)


def load_draft_file(draft_id: str) -> dict:
    data_path = os.path.join(app.root_path, 'data/', f'bans_{draft_id}.json')
    #with filelock.SoftFileLock(data_path):
    draft_json = json.load(open(data_path, 'r'))
    return draft_json


def update_draft_file(draft_id: str, draft_json: dict) -> dict:
    data_path = os.path.join(app.root_path, 'data/', f'bans_{draft_id}.json')
    #draft_json = {k:v for k, v in draft_json.items() if v}

    #with filelock.SoftFileLock(data_path):
    #draft_json_new = json.load(open(data_path, 'r'))
    #draft_json_new.update(draft_json)
    #json.dump(draft_json_new, open(data_path, 'w'))
    #return draft_json_new
    json.dump(draft_json, open(data_path, 'w'))
    return draft_json

def load_icon_lists():
    # Load civ and map icon lists from icons.json
    global civs_icon_list, maps_icon_list
    lists = json.load(open(os.path.join(app.root_path, 'icons.json'), 'r'))
    maps_icon_list = lists['maps_icon_list']
    civs_icon_list = lists['civs_icon_list']

@app.before_serving
async def init_server():
    global pool

    pool = await asyncpg.create_pool(
        user=dbuser,
        password=dbpass,
        host=dbhost,
        port=dbport,
        database=dbname,
    )

    load_icon_lists()

@app.after_serving
async def close_server():
    global pool
    await pool.close()

@app.route("/")
async def index():
    return await render_template("index.html")


@app.route("/new/<string:draft_template>")
async def new_draft(draft_template: str):
    draft_json = {
        'template': draft_template,
        'draft_id': None,
        'rounds': 0,
        'map_bans': 0,
        'civ_bans': 0,
        'insta_bans': 0,
        'draft_stage': 'bans', # bans, waiting_round, round,
        'round_numb' : -1,
        'actions': [],
        'available_maps': [],
        'available_civs': [],
        'host_insta_bans': 0,
        'guest_insta_bans' : 0,
    }
    if draft_template == 'bo3':
        draft_json.update({
            'rounds': 3,
            'map_bans': 3,
            'civ_bans': 3,
            'insta_bans': 1,
        })
    elif draft_template == 'bo5':
        draft_json.update({
            'rounds': 5,
            'map_bans': 3,
            'civ_bans': 5,
            'insta_bans': 1,
        })
    elif draft_template == 'bo7':
        draft_json.update({
            'rounds': 7,
            'map_bans': 3,
            'civ_bans': 7,
            'insta_bans': 2,
        })
    else:
        return f'No template for: "{draft_template}"', 404

    data_dir = os.path.join(app.root_path, 'data/')
    if not os.path.exists(data_dir):
        os.mkdir(data_dir)
    file_desc, file_path = tempfile.mkstemp(prefix='bans_', suffix='.json', dir=data_dir)
    file_obj = os.fdopen(file_desc, 'w')
    code_match = re.match('.*data/bans_(.+)\\.json', file_path)
    if not code_match:
        raise Exception(f'data file doesnt match expected format: {file_path}')
    draft_id = code_match.groups()[0]
    draft_json['draft_id'] = draft_id

    json.dump(draft_json, file_obj)
    file_obj.close()

    return redirect(url_for(f'host_draft', draft_id=draft_id))


@app.route("/host/<string:draft_id>")
async def host_draft(draft_id: str):
    try:
        draft_json = load_draft_file(draft_id)
    except FileNotFoundError:
        return f"Couldn't load draft {draft_id}.", 404
    template_params = {
        'type': 'host',
        'draft_id': draft_id,
        'maps_list': maps_icon_list,
        'civs_list': civs_icon_list,
        'rounds': draft_json['rounds'],
        'map_bans': draft_json['map_bans'],
        'civ_bans': draft_json['civ_bans'],
        'insta_bans': draft_json['insta_bans'],
    }
    return await render_template("bans.html", **template_params)


@app.route("/join/<string:draft_id>")
async def join_draft(draft_id: str):
    try:
        draft_json = load_draft_file(draft_id)
    except FileNotFoundError:
        return f"Couldn't load draft {draft_id}.", 404
    template_params = {
        'type': 'join',
        'draft_id': draft_id,
        'maps_list': maps_icon_list,
        'civs_list': civs_icon_list,
        'rounds': draft_json['rounds'],
        'map_bans': draft_json['map_bans'],
        'civ_bans': draft_json['civ_bans'],
        'insta_bans': draft_json['insta_bans'],
    }
    return await render_template("bans.html", **template_params)

@app.route("/watch/<string:draft_id>")
async def watch_draft(draft_id: str):
    try:
        draft_json = load_draft_file(draft_id)
    except FileNotFoundError:
        return f"Couldn't load draft {draft_id}.", 404
    template_params = {
        'type': 'watch',
        'draft_id': draft_id,
        'maps_list': maps_icon_list,
        'civs_list': civs_icon_list,
        'rounds': draft_json['rounds'],
        'map_bans': draft_json['map_bans'],
        'civ_bans': draft_json['civ_bans'],
        'insta_bans': draft_json['insta_bans'],
    }
    return await render_template("bans.html", **template_params)


def validate_bans(draft_json: dict, bans_json: dict) -> Union[str, None]:
    if 'action' not in bans_json:
        return 'Missing action'
    if bans_json['action'] != 'submit_bans':
        return 'Unrecognized action'
    if 'map_bans' not in bans_json:
        return 'Missing map_bans'
    if not isinstance(bans_json['map_bans'], list):
        return 'map_bans not a list'
    if len(bans_json['map_bans']) != draft_json['map_bans']:
        return f'Wrong number of map bans: {len(bans_json["map_bans"])}'
    for map_id in bans_json['map_bans']:
        if map_id not in maps_icon_list:
            return f'Unrecognized map: {map_id}'
    if 'civ_bans' not in bans_json:
        return 'Missing civ_bans'
    if not isinstance(bans_json['civ_bans'], list):
        return 'civ_bans not a list'
    if len(bans_json['civ_bans']) != draft_json['civ_bans']:
        return f'Wrong number of civ bans: {len(bans_json["civ_bans"])}'
    for civ_id in bans_json['civ_bans']:
        if civ_id not in civs_icon_list:
            return f'Unrecognized civ: {civ_id}'

    return None


@app.websocket('/host/ws/<string:draft_id>')
async def host_ws(draft_id: str):
    global connected_hosts, connected_guests, connected_hosts_ip, connected_guests_ip
    if draft_id not in connected_hosts_ip:
        connected_hosts_ip[draft_id] = websocket.remote_addr
    if connected_hosts_ip[draft_id] != websocket.remote_addr:
        await websocket.send_json({'response': 'Host already connected for this draft.'})
        return
    if draft_id not in connected_hosts:
        connected_hosts[draft_id] = None

    try:
        while True:
            try:
                recv_json = await websocket.receive_json()
            except json.decoder.JSONDecodeError:
                await websocket.send_json({'response': 'Invalid request format.'})
                return
            try:
                draft_json = load_draft_file(draft_id)
            except FileNotFoundError:
                await websocket.send_json({'response': f'Invalid json draft id {draft_id}.'})
                continue
            if 'action' not in recv_json:
                await websocket.send_json({'response': 'Invalid json package. Try to refresh page (ctrl+shift+R).'})
                continue
            if recv_json['action'] == 'submit_bans':
                # is it the right stage?
                if draft_json['draft_stage'] != 'bans':
                    await websocket.send_json({'response': 'Bans cannot be submitted at this stage.'})
                    continue
                # have you submitted bans before?
                if connected_hosts[draft_id]:
                    await websocket.send_json({'response': 'Bans already submitted, waiting for guest.'})
                    continue
                # are the bans valid?
                valid_resp = validate_bans(draft_json, recv_json)
                recv_json = {k: recv_json[k] for k in ['action', 'map_bans', 'civ_bans']}
                if valid_resp is not None:
                    await websocket.send_json({'response': valid_resp})
                    continue
                connected_hosts[draft_id] = recv_json
                await websocket.send_json({'response': 'ok'})

                # has the guest submitted his bans?
                if draft_id in connected_guests and connected_guests[draft_id]:
                    draft_json = await broadcast_bans_update(draft_json)

            elif recv_json['action'] == 'next_round':
                # is it the right stage?
                if draft_json['draft_stage'] != 'waiting_round':
                    await websocket.send_json({'response': 'Next round cannot be started at this stage.'})
                    continue
                await broadcast_round_start(draft_id)

            elif recv_json['action'] == 'insta_ban':
                # is it the right stage?
                if draft_json['draft_stage'] != 'host_round':
                    await websocket.send_json({'response': 'Host cannot insta ban at this stage.'})
                    continue
                # do we still have insta bans?
                if draft_json['host_insta_bans'] >= draft_json['insta_bans']:
                    await websocket.send_json({'response': 'No insta bans remaining.'})
                    continue
                if recv_json['target'] not in ['host_civ', 'guest_civ']:
                    await websocket.send_json({'response': 'Invalid target for insta ban.'})
                    continue
                await broadcast_instaban(draft_id, 'host', recv_json['target'])

            elif recv_json['action'] == 'ready_round':
                # is it the right stage?
                if draft_json['draft_stage'] != 'host_round':
                    await websocket.send_json({'response': 'Host cannot continue round at this stage.'})
                    continue
                await broadcast_round_progress(draft_json)
    finally:
        connected_hosts.pop(draft_id)


@app.websocket('/join/ws/<string:draft_id>')
async def join_ws(draft_id: str):
    global connected_guests, connected_guests_ip
    if draft_id not in connected_guests_ip:
        connected_guests_ip[draft_id] = websocket.remote_addr
    if connected_guests_ip[draft_id] != websocket.remote_addr:
        await websocket.send_json({'response': 'Guest already connected.'})
        return
    if draft_id not in connected_guests:
        connected_guests[draft_id] = None
    
    try:
        while True:
            try:
                recv_json = await websocket.receive_json()
            except json.decoder.JSONDecodeError:
                await websocket.send_json({'response': 'Invalid request format.'})
                return
            try:
                draft_json = load_draft_file(draft_id)
            except FileNotFoundError:
                await websocket.send_json({'response': f'Invalid json draft id {draft_id}.'})
                continue
            if 'action' not in recv_json:
                await websocket.send_json({'response': 'Invalid json package. Try to refresh page (ctrl+shift+R).'})
                continue
            if recv_json['action'] == 'submit_bans':
                # is it the right stage?
                if draft_json['draft_stage'] != 'bans':
                    await websocket.send_json({'response': 'Bans cannot be submitted at this stage.'})
                    continue
                # have you submitted bans before?
                if connected_guests[draft_id]:
                    await websocket.send_json({'response': 'Bans already submitted, waiting for host.'})
                    continue
                # are the bans valid?
                valid_resp = validate_bans(draft_json, recv_json)
                recv_json = {k: recv_json[k] for k in ['action', 'map_bans', 'civ_bans']}
                if valid_resp is not None:
                    await websocket.send_json({'response': valid_resp})
                    continue
                connected_guests[draft_id] = recv_json
                await websocket.send_json({'response': 'ok'})

                # has the guest submitted his bans?
                if draft_id in connected_hosts and connected_hosts[draft_id]:
                    draft_json = await broadcast_bans_update(draft_json)

            elif recv_json['action'] == 'next_round':
                # is it the right stage?
                if draft_json['draft_stage'] != 'waiting_round':
                    await websocket.send_json({'response': 'Next round cannot be started at this stage.'})
                    continue
                await broadcast_round_start(draft_id)

            elif recv_json['action'] == 'insta_ban':
                # is it the right stage?
                if draft_json['draft_stage'] != 'guest_round':
                    await websocket.send_json({'response': 'Guest cannot insta ban at this stage.'})
                    continue
                # do we still have insta bans?
                if draft_json['guest_insta_bans'] >= draft_json['insta_bans']:
                    await websocket.send_json({'response': 'No insta bans remaining.'})
                    continue
                if recv_json['target'] not in ['host_civ', 'guest_civ']:
                    await websocket.send_json({'response': 'Invalid target for insta ban.'})
                    continue
                await broadcast_instaban(draft_id, 'guest', recv_json['target'])

            elif recv_json['action'] == 'ready_round':
                # is it the right stage?
                if draft_json['draft_stage'] != 'guest_round':
                    await websocket.send_json({'response': 'Guest cannot continue round at this stage.'})
                    continue
                await broadcast_round_progress(draft_json)

    finally:
        connected_guests.pop(draft_id)


connected_hosts = {}
connected_guests = {}
connected_hosts_ip = {}
connected_guests_ip = {}

async def broadcast_bans_update(draft_json):
    global connected_hosts, connected_guests
    draft_id = draft_json['draft_id']
    host_bans = connected_hosts[draft_id]
    guest_bans = connected_guests[draft_id]
    connected_hosts[draft_id] = None
    connected_guests[draft_id] = None

    draft_json['available_maps'] = [k for k in maps_icon_list
                                    if k not in host_bans['map_bans']
                                    and k not in guest_bans['map_bans']]
    draft_json['available_civs'] = [k for k in civs_icon_list
                                    if k not in host_bans['civ_bans']
                                    and k not in guest_bans['civ_bans']]

    action_json = {'action': 'update_bans',
                   'host_bans': host_bans,
                   'guest_bans': guest_bans,
                   }
    draft_json['actions'].append(action_json)
    draft_json['draft_stage'] = 'waiting_round'
    draft_json = update_draft_file(draft_id, draft_json)

    await broadcast_update(action_json, draft_json['draft_id'])
    return draft_json


async def broadcast_round_start(draft_id):
    global connected_hosts, connected_guests
    draft_json = load_draft_file(draft_id)
    if draft_json['draft_stage'] != 'waiting_round':
        return
    connected_hosts[draft_id] = None
    connected_guests[draft_id] = None

    draft_json['round_numb'] += 1
    i = random.randint(0, len(draft_json['available_maps'])-1)
    map_id = draft_json['available_maps'].pop(i)
    i = random.randint(0, len(draft_json['available_civs'])-1)
    host_civ_id = draft_json['available_civs'].pop(i)
    i = random.randint(0, len(draft_json['available_civs'])-1)
    guest_civ_id = draft_json['available_civs'].pop(i)

    action_json = {'action': 'start_round',
                   'round_numb': draft_json['round_numb'],
                   'map': map_id,
                   'host_civ': host_civ_id,
                   'guest_civ': guest_civ_id,
                   }
    draft_json['actions'].append(action_json)
    if draft_json['round_numb']%2 == 0:
        draft_json['draft_stage'] = 'host_round'
    else:
        draft_json['draft_stage'] = 'guest_round'
    draft_json = update_draft_file(draft_id, draft_json)

    bu_pending = broadcast_update(action_json, draft_json['draft_id'])

    action_json = {
        'action': 'ready_round',
        'round_numb': draft_json['round_numb'],
    }

    if draft_json['draft_stage'] == 'host_round':
        action_json['target'] = 'host'
    else:
        action_json['target'] = 'join'
    draft_json['actions'].append(action_json)
    draft_json = update_draft_file(draft_id, draft_json)

    await bu_pending
    await broadcast_update(action_json, draft_json['draft_id'])
    return draft_json


async def broadcast_round_progress(draft_json):
    draft_id = draft_json['draft_id']
    r = draft_json['round_numb']
    action_json = {}
    if r%2 == 0: # host first, guest second
        if draft_json['draft_stage'] == 'host_round':
            next_stage = 'guest_round'
            action_json = {
                'action': 'ready_round',
                'target': 'join',
            }

        elif draft_json['draft_stage'] == 'guest_round':
            next_stage = 'waiting_round'
            action_json = {'action': 'finish_round'}

    else: # guest first, host second
        if draft_json['draft_stage'] == 'guest_round':
            next_stage = 'host_round'
            action_json = {
                'action': 'ready_round',
                'target': 'host',
            }
        elif draft_json['draft_stage'] == 'host_round':
            next_stage = 'waiting_round'
            action_json = {'action': 'finish_round'}

    action_json['round_numb'] = r
    draft_json['draft_stage'] = next_stage
    draft_json['actions'].append(action_json)
    draft_json = update_draft_file(draft_id, draft_json)

    await broadcast_update(action_json, draft_id)
    return draft_json

async def broadcast_instaban(draft_id, user, target):
    draft_json = load_draft_file(draft_id)
    if user == 'host' and draft_json['draft_stage'] != 'host_round':
        return
    if user == 'guest' and draft_json['draft_stage'] != 'guest_round':
        return

    if user == 'host':
        if draft_json['host_insta_bans'] >= draft_json['insta_bans']:
            return
        draft_json['host_insta_bans'] += 1
    elif user == 'guest':
        if draft_json['guest_insta_bans'] >= draft_json['insta_bans']:
            return
        draft_json['guest_insta_bans'] += 1

    i = random.randint(0, len(draft_json['available_civs']))
    new_civ = draft_json['available_civs'].pop(i)

    action_json = {
        'action': 'update_instaban',
        'target': target,
        'new_civ': new_civ,
        'user': user,
        'round_numb': draft_json['round_numb'],
    }
    draft_json['actions'].append(action_json)
    draft_json = update_draft_file(draft_id, draft_json)
    await broadcast_update(action_json, draft_id)
    return


connected_watchers = {}


def collect_websocket(func):
    @wraps(func)
    async def wrapper(draft_id):
        global connected_watchers
        queue = asyncio.Queue()

        if draft_id not in connected_watchers:
            connected_watchers[draft_id] = set()
        con_watcher_set = connected_watchers[draft_id]
        con_watcher_set.add(queue)
        try:
            return await func(queue, draft_id)
        finally:
            con_watcher_set.remove(queue)
            if len(con_watcher_set) == 0:
                connected_watchers.pop(draft_id)

    return wrapper


@app.websocket('/watch/ws/<string:draft_id>')
@collect_websocket
async def watch_ws(queue: asyncio.Queue, draft_id: str):
    draft_json = load_draft_file(draft_id)
    await websocket.send_json(draft_json)

    while True:
        data = await queue.get()
        await websocket.send_json(data)


async def broadcast_update(update_json: dict, draft_id: str):
    print("broadcasting")
    con_watch_queues = connected_watchers.get(draft_id)
    if con_watch_queues:
        for queue in con_watch_queues:
            await queue.put(update_json)


if __name__ == "__main__":
    app.run()
