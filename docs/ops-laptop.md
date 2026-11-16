# 운영 노트북 영구 설정 (#103)

행사 운영 노트북(Agent 실행 PC)의 화면·전원 설정을 재부팅 뒤에도 유지되게 하는 기준과 점검·복구 절차다.
설정 변경(아래 `sudo` 명령)은 운영자가 직접 한다. 점검 스크립트는 읽기 전용이다.

## 점검

```bash
python3 scripts/ops_laptop_check.py   # 그래픽 세션의 터미널에서 실행
```

항목별 `[PASS|FAIL|UNKNOWN]` 과 마지막 한 줄(`OK`/`FAIL`/`CHECK`)을 출력한다. `UNKNOWN` 은 SSH 처럼
그래픽 세션이 아니라 `gsettings`·`xrandr` 를 읽지 못한 경우다.

| 항목 | 기준(영구 설정) |
|---|---|
| Xorg 기본 세션 | `/etc/gdm3/custom.conf` `[daemon]` 에 `WaylandEnable=false` |
| 덮개 닫힘 무시 | `/etc/systemd/logind.conf.d/50-poppy-lid.conf` 에 `HandleLidSwitch=ignore`, `HandleLidSwitchExternalPower=ignore`, `HandleLidSwitchDocked=ignore` |
| 절전 target mask | `sleep.target`, `suspend.target`, `hibernate.target`, `hybrid-sleep.target` 가 `/dev/null` 로 mask |
| GNOME 자동 절전·화면 끄기 | `sleep-inactive-ac-type`·`sleep-inactive-battery-type` = `'nothing'`, `idle-delay` = `uint32 0` |
| 외부 모니터 1080p60 | 외부 출력(eDP 제외)의 현재 모드 1920x1080, 60 Hz |

## 설정 (운영자, 1회)

```bash
sudo sed -i 's/^#\?WaylandEnable=.*/WaylandEnable=false/' /etc/gdm3/custom.conf
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n' \
  | sudo tee /etc/systemd/logind.conf.d/50-poppy-lid.conf
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
gsettings set org.gnome.desktop.session idle-delay 0
```

GDM·logind 설정은 재부팅 후 적용된다(행사 중 `systemctl restart systemd-logind`/`gdm3` 는 세션을 끊으므로 하지 않는다).
1080p60 은 GNOME 디스플레이 설정에서 외부 모니터를 1920×1080, 60 Hz 로 고르고 "변경 사항 유지"를 누르면
`~/.config/monitors.xml` 에 저장되어 같은 모니터를 다시 연결하면 복원된다.

## 현장 체크리스트

- [ ] 재부팅 → 자동 로그인 후 `ops_laptop_check.py` 가 `OK`
- [ ] 덮개 닫고 1분 → Agent `status.json` `observedAt` 이 계속 갱신(절전 안 함)
- [ ] 외부 모니터 분리 → 재연결: 1080p60 복원, 점검 `OK`
- [ ] 외부 모니터 연결 상태로 재부팅: 1080p60 유지
- [ ] 결과(날짜, 모니터 모델, 항목별 결과)를 `docs/trial-records/` 에 기록

## 복구

- 1080p60 이 아니면 디스플레이 설정에서 다시 고른다. 안 되면 `~/.config/monitors.xml` 을 백업 후 지우고 재로그인해 다시 고른다.
- Wayland 로 로그인됐으면(`echo $XDG_SESSION_TYPE` 이 `wayland`) `custom.conf` 를 확인하고 재부팅한다.
- 덮개를 닫았는데 절전되면 `50-poppy-lid.conf` 와 mask 를 확인하고 재부팅한다.
