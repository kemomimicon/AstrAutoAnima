"""Public deployments never execute private cloud startup scripts or kill guessed PIDs."""

def recovery_config():
    return {'enabled': False, 'message': '公共版请使用部署目录内 Start.cmd / Start.sh 启动；重启前请正常停止各服务。'}


def read_status(root):
    return {'state': 'idle'}


def submit(root, actor):
    raise ValueError(recovery_config()['message'])
