#!/bin/sh
set -eu
umask 077
# Saved image contains no host private keys. Each instance generates its own.
/usr/bin/ssh-keygen -A
exec /usr/lib/aaa-image/sshd.real "$@"
