import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.firebase.appdistribution")
}

// 릴리스 서명 정보는 git에 올리지 않는 keystore.properties에서 읽는다(있을 때만).
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) keystorePropsFile.inputStream().use { load(it) }
}

// Firebase App Distribution 설정도 git에 올리지 않는 firebase.properties에서 읽는다(있을 때만).
val firebasePropsFile = rootProject.file("firebase.properties")
val firebaseProps = Properties().apply {
    if (firebasePropsFile.exists()) firebasePropsFile.inputStream().use { load(it) }
}

android {
    namespace = "com.samsung.ac.bridge"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.samsung.ac.bridge"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("release") {
            if (keystoreProps.isNotEmpty()) {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // keystore.properties가 있을 때만 릴리스 서명 적용(없으면 unsigned 로 빌드)
            if (keystoreProps.isNotEmpty()) {
                signingConfig = signingConfigs.getByName("release")
            }

            // Firebase App Distribution 업로드 설정. 값은 firebase.properties / 서비스계정 키에서.
            //   업로드:  ./gradlew assembleRelease appDistributionUploadRelease
            firebaseAppDistribution {
                appId = firebaseProps.getProperty("appId") ?: ""
                artifactType = "APK"
                // 테스터 그룹(쉼표 구분). Firebase 콘솔에서 만든 그룹 별칭.
                groups = firebaseProps.getProperty("groups") ?: ""
                serviceCredentialsFile = rootProject.file("firebase-service-account.json").absolutePath
                releaseNotes = firebaseProps.getProperty("releaseNotes") ?: "AC Bridge release"
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = "11"
    }

    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    // Core
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.activity:activity-ktx:1.8.0")
    implementation("com.google.android.material:material:1.10.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // JSON
    implementation("com.google.code.gson:gson:2.10.1")

    // Testing
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}
