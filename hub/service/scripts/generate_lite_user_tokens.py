from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import secrets
from pathlib import Path


QQ_PATTERN = re.compile(r"^[1-9][0-9]{4,14}$")


def _exclusive_text(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("x", encoding="utf-8", newline="")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="为 QQ 列表生成一人一令牌的 Hub 注册表与私密交付表。"
    )
    parser.add_argument("--qq-file", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    args = parser.parse_args()

    if args.registry.exists() or args.delivery.exists():
        raise SystemExit("目标文件已存在；为避免覆盖令牌，请更换文件名")

    values = [
        line.strip()
        for line in args.qq_file.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    invalid = [value for value in values if not QQ_PATTERN.fullmatch(value)]
    if invalid:
        raise SystemExit(f"QQ 文件含无效行，共 {len(invalid)} 行")
    if len(values) != len(set(values)):
        raise SystemExit("QQ 文件含重复号码")
    if not values:
        raise SystemExit("QQ 文件为空")

    registry_users: list[dict[str, object]] = []
    delivery_rows: list[tuple[str, str]] = []
    for qq in values:
        token = f"aah_u_{secrets.token_urlsafe(32)}"
        registry_users.append(
            {
                "id": f"qq-{qq}",
                "label": f"QQ {qq}",
                "qq": qq,
                "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "allow_group": True,
                "enabled": True,
            }
        )
        delivery_rows.append((qq, token))

    registry_payload = {"version": 1, "users": registry_users}
    with _exclusive_text(args.registry) as handle:
        json.dump(registry_payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with _exclusive_text(args.delivery) as handle:
        writer = csv.writer(handle)
        writer.writerow(["qq", "token"])
        writer.writerows(delivery_rows)
    os.chmod(args.registry, 0o600)
    os.chmod(args.delivery, 0o600)
    print(f"已生成 {len(values)} 个绑定令牌")
    print(f"服务端注册表：{args.registry}")
    print(f"私密交付表：{args.delivery}")
    print("交付表含令牌明文，请勿上传到群聊、Git 或公开网盘。")


if __name__ == "__main__":
    main()
