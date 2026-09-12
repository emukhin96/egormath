from django.db import migrations


def copy_topics_to_collection_parents(apps, schema_editor):
    """Родительский раздел получает объединение тем дочерних подборок."""
    Collection = apps.get_model('worksheets', 'Collection')
    Worksheet = apps.get_model('worksheets', 'Worksheet')
    through = Worksheet.topics.through
    collections = list(Collection.objects.values(
        'id', 'parent_id', 'worksheet_id'))
    parent_by_id = {row['id']: row['parent_id'] for row in collections}
    worksheet_by_id = {row['id']: row['worksheet_id'] for row in collections}
    collection_by_worksheet = {
        row['worksheet_id']: row['id'] for row in collections}
    topic_rows = list(through.objects.values('worksheet_id', 'topic_id'))
    additions = set()
    for row in topic_rows:
        collection_id = collection_by_worksheet.get(row['worksheet_id'])
        parent_id = parent_by_id.get(collection_id)
        while parent_id is not None:
            additions.add((worksheet_by_id[parent_id], row['topic_id']))
            parent_id = parent_by_id.get(parent_id)
    through.objects.bulk_create([
        through(worksheet_id=worksheet_id, topic_id=topic_id)
        for worksheet_id, topic_id in additions
    ], ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0016_rubric_note_textfield'),
    ]

    operations = [
        migrations.RunPython(
            copy_topics_to_collection_parents,
            migrations.RunPython.noop,
        ),
    ]
