"""A* grid navigation + path smoothing for Spectro / Amethyst.

Drop this file next to play.py. It is self-contained (only math + heapq),
so it does not change any existing behavior until you wire it into get_movement.

Coordinate convention matches the bot:
  - All positions are screen pixels (x right, y DOWN).
  - Heading angle: 0=right, 90=down, 180=left, 270=up  (atan2(dy, dx)).
  - walls are boxes [x1, y1, x2, y2] in pixels.
"""
import heapq
import math

_SQRT2 = math.sqrt(2.0)


def _segment_hits_rect(x0, y0, x1, y1, rx1, ry1, rx2, ry2):
    """Liang-Barsky: True if segment (x0,y0)-(x1,y1) intersects axis-aligned
    rectangle [rx1,ry1,rx2,ry2]. Pure python, no cv2 needed."""
    dx = x1 - x0
    dy = y1 - y0
    # Trivial: endpoint inside rect
    if rx1 <= x0 <= rx2 and ry1 <= y0 <= ry2:
        return True
    if rx1 <= x1 <= rx2 and ry1 <= y1 <= ry2:
        return True
    p = [-dx, dx, -dy, dy]
    q = [x0 - rx1, rx2 - x0, y0 - ry1, ry2 - y0]
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return False  # parallel and outside
        else:
            t = qi / pi
            if pi < 0:
                if t > u2:
                    return False
                if t > u1:
                    u1 = t
            else:
                if t < u1:
                    return False
                if t < u2:
                    u2 = t
    return u1 <= u2


def segment_blocked(p1, p2, walls, padding=0.0):
    """True if straight line p1->p2 crosses any (padded) wall box.
    Mirrors play.walls_block_line_of_sight but pure-python."""
    if not walls:
        return False
    x0, y0 = p1
    x1, y1 = p2
    for w in walls:
        wx1, wy1, wx2, wy2 = w[0] - padding, w[1] - padding, w[2] + padding, w[3] + padding
        if _segment_hits_rect(x0, y0, x1, y1, wx1, wy1, wx2, wy2):
            return True
    return False


class GridNavigator:
    def __init__(self, cell_size=30.0, grid_radius_cells=16, inflate=34.0):
        self.cell = float(cell_size)
        self.R = int(grid_radius_cells)
        self.inflate = float(inflate)

    def _cell_blocked(self, cx, cy, infl_walls):
        for (x1, y1, x2, y2) in infl_walls:
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                return True
        return False

    def find_path_cells(self, player_pos, target_pos, walls):
        R, cell = self.R, self.cell
        px, py = player_pos
        # Pre-inflate walls once
        infl = [(w[0]-self.inflate, w[1]-self.inflate, w[2]+self.inflate, w[3]+self.inflate) for w in (walls or [])]

        def world(i, j):
            return (px + i*cell, py + j*cell)

        def blocked(i, j):
            cx, cy = world(i, j)
            return self._cell_blocked(cx, cy, infl)

        # Goal cell = clamp target direction into grid
        tx, ty = target_pos
        gi = max(-R, min(R, int(round((tx - px)/cell))))
        gj = max(-R, min(R, int(round((ty - py)/cell))))
        # If goal blocked, spiral out to nearest free cell
        if blocked(gi, gj):
            best = None
            for rad in range(1, R+1):
                for di in range(-rad, rad+1):
                    for dj in range(-rad, rad+1):
                        ni, nj = gi+di, gj+dj
                        if abs(ni) > R or abs(nj) > R:
                            continue
                        if not blocked(ni, nj):
                            d = di*di + dj*dj
                            if best is None or d < best[0]:
                                best = (d, ni, nj)
                if best:
                    break
            if not best:
                return None
            gi, gj = best[1], best[2]

        start = (0, 0)
        goal = (gi, gj)
        if start == goal:
            return [start]

        open_heap = [(0.0, start)]
        gscore = {start: 0.0}
        came = {}
        neighbors = [(-1,0,1.0),(1,0,1.0),(0,-1,1.0),(0,1,1.0),
                     (-1,-1,_SQRT2),(-1,1,_SQRT2),(1,-1,_SQRT2),(1,1,_SQRT2)]

        def h(i, j):
            di, dj = abs(i-gi), abs(j-gj)
            return (di+dj) + (_SQRT2-2)*min(di, dj)  # octile

        closed = set()
        while open_heap:
            _, cur = heapq.heappop(open_heap)
            if cur in closed:
                continue
            if cur == goal:
                path = [cur]
                while cur in came:
                    cur = came[cur]
                    path.append(cur)
                path.reverse()
                return path
            closed.add(cur)
            ci, cj = cur
            for di, dj, cost in neighbors:
                ni, nj = ci+di, cj+dj
                if abs(ni) > R or abs(nj) > R:
                    continue
                if blocked(ni, nj):
                    continue
                if di != 0 and dj != 0:
                    # no corner cutting
                    if blocked(ci+di, cj) or blocked(ci, cj+dj):
                        continue
                ng = gscore[cur] + cost
                nxt = (ni, nj)
                if ng < gscore.get(nxt, 1e18):
                    gscore[nxt] = ng
                    came[nxt] = cur
                    heapq.heappush(open_heap, (ng + h(ni, nj), nxt))
        return None

    def _path_to_heading(self, player_pos, cells, walls, los_padding=28.0):
        if not cells or len(cells) < 2:
            return None
        px, py = player_pos
        cell = self.cell
        pts = [(px + i*cell, py + j*cell) for (i, j) in cells]
        # String-pull: farthest waypoint reachable by clear straight line.
        chosen = pts[1]
        for pt in reversed(pts[1:]):
            if not segment_blocked(player_pos, pt, walls, padding=los_padding):
                chosen = pt
                break
        dx, dy = chosen[0]-px, chosen[1]-py
        if dx == 0 and dy == 0:
            return None
        return math.degrees(math.atan2(dy, dx)) % 360

    def next_heading(self, player_pos, target_pos, walls, los_padding=28.0):
        """Return a heading angle (deg) toward the target along an A* route,
        with string-pulling. None if no route (caller should fall back)."""
        cells = self.find_path_cells(player_pos, target_pos, walls)
        return self._path_to_heading(player_pos, cells, walls, los_padding=los_padding)

    def find_upward_path_cells(self, player_pos, walls, min_progress_cells=None):
        """Find a local route whose goal is upward progress, not a fixed point.

        This is used when no enemy is visible. A fixed target directly above the
        player can make the bot hold the joystick straight up until it touches a
        wall. Here we search the whole local grid and pick the reachable cell
        with the best upward progress, then the smallest side drift and route
        length. The resulting path can start with a diagonal or side step to go
        around walls before colliding with them.
        """
        R, cell = self.R, self.cell
        px, py = player_pos
        infl = [(w[0]-self.inflate, w[1]-self.inflate, w[2]+self.inflate, w[3]+self.inflate) for w in (walls or [])]

        def world(i, j):
            return (px + i*cell, py + j*cell)

        def blocked(i, j):
            cx, cy = world(i, j)
            return self._cell_blocked(cx, cy, infl)

        start = (0, 0)
        if blocked(*start):
            return None

        neighbors = [
            (0,-1,1.0), (-1,-1,_SQRT2), (1,-1,_SQRT2),
            (-1,0,1.0), (1,0,1.0),
            (0,1,1.0), (-1,1,_SQRT2), (1,1,_SQRT2),
        ]
        open_heap = [(0.0, start)]
        gscore = {start: 0.0}
        came = {}
        closed = set()

        while open_heap:
            _, cur = heapq.heappop(open_heap)
            if cur in closed:
                continue
            closed.add(cur)
            ci, cj = cur
            for di, dj, cost in neighbors:
                ni, nj = ci+di, cj+dj
                if abs(ni) > R or abs(nj) > R:
                    continue
                if blocked(ni, nj):
                    continue
                if di != 0 and dj != 0:
                    # no corner cutting
                    if blocked(ci+di, cj) or blocked(ci, cj+dj):
                        continue
                ng = gscore[cur] + cost
                nxt = (ni, nj)
                if ng < gscore.get(nxt, 1e18):
                    gscore[nxt] = ng
                    came[nxt] = cur
                    # Strongly prefer upward cells, but keep Dijkstra-like cost.
                    priority = ng + max(0, nj) * 4.0 + abs(ni) * 0.02
                    heapq.heappush(open_heap, (priority, nxt))

        if len(closed) <= 1:
            return None

        if min_progress_cells is None:
            min_progress_cells = max(2, int(R * 0.45))
        min_progress_cells = max(1, min(R, int(min_progress_cells)))

        candidates = []
        for i, j in closed:
            progress = -j
            if progress <= 0:
                continue
            candidates.append((i, j, progress, gscore.get((i, j), 1e18)))
        if not candidates:
            return None

        # Prefer cells that reach at least the requested upward progress. If the
        # route is heavily blocked, still take the best available upward cell.
        strong = [c for c in candidates if c[2] >= min_progress_cells]
        pool = strong or candidates
        best_i, best_j, _, _ = min(
            pool,
            key=lambda c: (
                -c[2],          # more upward progress first
                abs(c[0]),      # less side drift second
                c[3],           # shorter route third
            ),
        )

        cur = (best_i, best_j)
        path = [cur]
        while cur in came:
            cur = came[cur]
            path.append(cur)
        path.reverse()
        return path

    def next_upward_heading(self, player_pos, walls, los_padding=28.0, min_progress_cells=None):
        """Return a heading for wall-aware upward roaming.

        If the player is already touching a wall, the current point can be
        inside the inflated wall area. In that case retry with smaller inflation
        so the pathfinder can produce an escape step instead of returning None.
        """
        cells = self.find_upward_path_cells(player_pos, walls, min_progress_cells=min_progress_cells)
        heading = self._path_to_heading(player_pos, cells, walls, los_padding=los_padding)
        if heading is not None:
            return heading

        if not walls or self.inflate <= 0:
            return None

        original_inflate = self.inflate
        try:
            for factor in (0.5, 0.25, 0.0):
                self.inflate = original_inflate * factor
                cells = self.find_upward_path_cells(player_pos, walls, min_progress_cells=min_progress_cells)
                heading = self._path_to_heading(
                    player_pos,
                    cells,
                    walls,
                    los_padding=min(float(los_padding), max(0.0, self.inflate)),
                )
                if heading is not None:
                    return heading
        finally:
            self.inflate = original_inflate
        return None
