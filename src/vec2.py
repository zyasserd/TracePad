import math
from dataclasses import dataclass

@dataclass
class Vec2:
    x: float
    y: float

    def __iter__(self):
        return iter((self.x, self.y))

    def __repr__(self) -> str:
        return f"Vec2(x={self.x}, y={self.y})"
    
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Vec2) and self.x == other.x and self.y == other.y
    
    def __add__(self, other: 'Vec2') -> 'Vec2':
        return Vec2(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other: 'Vec2') -> 'Vec2':
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, other) -> 'Vec2':
        if isinstance(other, (int, float)):  # Scalar multiplication
            return Vec2(self.x * other, self.y * other)
        elif isinstance(other, Vec2):        # element-wise multiplication
            return Vec2(self.x * other.x, self.y * other.y)
        else:
            return NotImplemented

    def __rmul__(self, other) -> 'Vec2':
        return self.__mul__(other)
    
    def dot(self, other: 'Vec2') -> float:
        return self.x * other.x + self.y * other.y

    def length(self) -> float:
        return math.hypot(self.x, self.y)
    
    def distance_to(self, other: 'Vec2') -> float:
        return (self - other).length()
    
    def transform_to_space(self, from_space: 'Vec2', to_space: 'Vec2') -> 'Vec2':
        """
        Transform this Vec2 from one coordinate space to another.
        from_space: Vec2 (source max_x, max_y)
        to_space: Vec2 (target width, height)
        """
        return Vec2(self.x * to_space.x / from_space.x, self.y * to_space.y / from_space.y)
    
    def distance_to_segment(self, a: 'Vec2', b: 'Vec2') -> float:
        """
        Returns the shortest distance from this point to the segment ab.
        """
        if a == b:
            return self.distance_to(a)
        
        ab = b - a
        ap = self - a
        ab_len2 = ab.dot(ab)
        t = ap.dot(ab) / ab_len2
        t = max(0, min(1, t))
        closest = a + ab * t
        return self.distance_to(closest)
    
    @property
    def aspect(self) -> float:
        """Return the aspect ratio x/y (width/height)."""
        return self.x / self.y if self.y != 0 else float('inf')
    
    @staticmethod
    def from_polar_coordinates(angle_rad: float, radius: float) -> 'Vec2':
        """Create a Vec2 from an angle in radians and a radius (length)."""
        return Vec2(math.cos(angle_rad) * radius, math.sin(angle_rad) * radius)

