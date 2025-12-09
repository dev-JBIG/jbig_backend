# Generated migration for populating JBIG info

from django.db import migrations


def populate_jbig_info(apps, schema_editor):
    SiteSettings = apps.get_model('jbig_backend', 'SiteSettings')
    
    # Default JBIG information
    defaults = {
        'jbig_description': "'JBIG'(JBNU Big Data & AI Group)은 데이터 사이언스와 딥러닝, 머신러닝을 포함한 AI에 대한 학술 교류를 목표로 2021년 설립된 전북대학교의 학생 학회입니다.",
        'jbig_president': '박성현',
        'jbig_president_dept': '전자공학부',
        'jbig_vice_president': '국환',
        'jbig_vice_president_dept': '사회학과',
        'jbig_email': 'green031234@naver.com',
        'jbig_advisor': '최규빈 교수님',
        'jbig_advisor_dept': '통계학과',
    }
    
    for key, value in defaults.items():
        SiteSettings.objects.get_or_create(key=key, defaults={'value': value})


def reverse_populate(apps, schema_editor):
    SiteSettings = apps.get_model('jbig_backend', 'SiteSettings')
    
    keys = [
        'jbig_description',
        'jbig_president',
        'jbig_president_dept',
        'jbig_vice_president',
        'jbig_vice_president_dept',
        'jbig_email',
        'jbig_advisor',
        'jbig_advisor_dept',
    ]
    
    SiteSettings.objects.filter(key__in=keys).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('jbig_backend', '0002_sitesettings'),
    ]

    operations = [
        migrations.RunPython(populate_jbig_info, reverse_populate),
    ]

