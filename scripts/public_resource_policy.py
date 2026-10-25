"""Keep unreviewed offline resource payloads out of public source and archives."""
from pathlib import PurePosixPath


def unreviewed_gufeng_payload(name):
    path = PurePosixPath(str(name).replace('\\', '/').lower())
    parts = path.parts
    resource_directory = any(parts[index:index + 2] in {
        ('optional', 'gufeng'), ('resources', 'gufeng')
    } for index in range(len(parts) - 1))
    if resource_directory:
        # Only the public declaration and installer documentation are approved.
        return not (parts[-2:] == ('gufeng', 'readme.md') or parts[-2:] == ('gufeng', 'package.json'))
    return path.name.startswith('gufeng-private-candidate-') and path.suffix == '.zip'


def require_public_resource(name):
    if unreviewed_gufeng_payload(name):
        raise ValueError('Unreviewed GuFeng resource payload cannot enter a public artifact: ' + str(name))
