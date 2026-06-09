# VPS 娴侀噺鐩戞帶

閫氳繃 `http://VPS_IP:9090` 璁块棶鐨勭綉椤电増娴侀噺鐩戞帶闈㈡澘銆?
## 榛樿閰嶇疆

- 璐﹀彿锛歚admin`
- 瀵嗙爜锛歚QQqq308008685`
- 绔彛锛歚9090`
- 鏁版嵁搴擄細`traffic.db`

## 鍔熻兘

- 瀹炴椂鏄剧ず褰撳墠涓婁紶銆佷笅杞介€熷害
- 瀹炴椂鏄剧ず褰撴湀绱涓婁紶銆佷笅杞芥祦閲?- 鏀寔閫夋嫨鎸囧畾鏈堜唤鏌ョ湅绱涓婁紶銆佷笅杞芥暟鎹?- 鏀寔閫夋嫨鍏ㄩ儴缃戝崱鎴栨煇涓綉鍗?- 浣跨敤 SQLite 鎸佷箙鍖栨湀浠界疮璁℃暟鎹?
## 閮ㄧ讲

鎶婃暣涓洰褰曚笂浼犲埌 VPS 鍚庢墽琛岋細

```bash
cd vps-traffic-monitor
chmod +x install.sh
sudo ./install.sh
```

濡傛灉 VPS 寮€浜嗛槻鐏锛岄渶瑕佹斁琛岀鍙ｏ細

```bash
sudo ufw allow 9090/tcp
```

鐒跺悗璁块棶锛?
```text
http://浣犵殑鏈嶅姟鍣↖P:9090
```

## 鎵嬪姩杩愯

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

