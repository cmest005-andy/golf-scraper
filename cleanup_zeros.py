from golf.models import PlayerScore
qs = PlayerScore.objects.filter(strokes=0, round__round_number__gte=3)
count = qs.count()
qs.delete()
print('Deleted', count, 'records')
