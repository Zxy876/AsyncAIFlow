from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

BASE = pathlib.Path('/tmp')
REQUEST_FILE = pathlib.Path('/Users/zxydediannao/AIWorkspace/ AsyncAIFlow/tmp/e2e-design-request.json')


def run() -> int:
    create_raw = subprocess.check_output(
        [
            'curl', '-sS', '--noproxy', '*',
            '-H', 'Content-Type: application/json',
            '-d', '@' + str(REQUEST_FILE),
            'http://localhost:8080/api/design/tasks',
        ],
        text=True,
    )
    (BASE / 'asyncaiflow_e2e_create.json').write_text(create_raw, encoding='utf-8')
    create_payload = json.loads(create_raw)
    task_id = create_payload['data']['taskId']
    (BASE / 'asyncaiflow_e2e_task_id.txt').write_text(task_id, encoding='utf-8')

    status = 'UNKNOWN'
    status_raw = ''
    for _ in range(120):
        status_raw = subprocess.check_output(
            ['curl', '-sS', '--noproxy', '*', f'http://localhost:8080/api/design/tasks/{task_id}/status'],
            text=True,
        )
        (BASE / 'asyncaiflow_e2e_status.json').write_text(status_raw, encoding='utf-8')
        status = json.loads(status_raw)['data']['status']
        if status in ('SUCCEEDED', 'FAILED'):
            break
        time.sleep(2)

    result_raw = subprocess.run(
        ['curl', '-sS', '--noproxy', '*', f'http://localhost:8080/api/design/tasks/{task_id}/result'],
        text=True,
        capture_output=True,
        check=False,
    ).stdout
    (BASE / 'asyncaiflow_e2e_result.json').write_text(result_raw, encoding='utf-8')

    workflow_id = subprocess.check_output(
        [
            'docker', 'compose', 'exec', '-T', 'mysql', 'mysql',
            '-uroot', '-proot', '-N', '-B', 'asyncaiflow',
            '-e', f"select workflow_id from design_task where id='{task_id}'",
        ],
        text=True,
    ).strip()
    (BASE / 'asyncaiflow_e2e_workflow_id.txt').write_text(workflow_id, encoding='utf-8')

    actions_raw = subprocess.check_output(
        ['curl', '-sS', '--noproxy', '*', f'http://localhost:8080/workflow/{workflow_id}/actions'],
        text=True,
    )
    (BASE / 'asyncaiflow_e2e_actions.json').write_text(actions_raw, encoding='utf-8')
    actions_payload = json.loads(actions_raw)

    details: dict[str, object] = {}
    for action in actions_payload['data']:
        action_id = action['actionId']
        detail_raw = subprocess.check_output(
            ['curl', '-sS', '--noproxy', '*', f'http://localhost:8080/action/{action_id}'],
            text=True,
        )
        details[str(action_id)] = json.loads(detail_raw)['data']
    (BASE / 'asyncaiflow_e2e_action_details.json').write_text(json.dumps(details, ensure_ascii=False), encoding='utf-8')

    print(json.dumps({'taskId': task_id, 'workflowId': workflow_id, 'finalStatus': status}, ensure_ascii=False))
    return 0 if status == 'SUCCEEDED' else 2


if __name__ == '__main__':
    raise SystemExit(run())
