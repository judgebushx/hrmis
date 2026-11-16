from django.db import models

class Island(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    def __str__(self): return self.name

class Municipality(models.Model):
    island = models.ForeignKey(Island, on_delete=models.PROTECT, related_name="municipalities")
    name = models.CharField(max_length=100)
    class Meta: unique_together = ("island", "name")
    def __str__(self): return f"{self.name}, {self.island.name}"

class Village(models.Model):
    municipality = models.ForeignKey(Municipality, on_delete=models.PROTECT, related_name="villages")
    name = models.CharField(max_length=100)
    class Meta: unique_together = ("municipality", "name")
    def __str__(self): return f"{self.name}, {self.municipality}"
