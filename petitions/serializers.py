from rest_framework import serializers

class GenerateSerializer(serializers.Serializer):
    template_id = serializers.IntegerField()
    data = serializers.DictField()
